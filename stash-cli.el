;;; stash-cli.el --- Emacs integration for stash-cli -*- lexical-binding: t; -*-

;; Author: Juan Gonzalez
;; Keywords: tools, vc
;; Package-Requires: ((emacs "30.1"))

;;; Commentary:

;; Integrates the Python `stash-cli` tool with Emacs, with an emphasis on
;; reviewing the current branch pull request and its code review comments.

;;; Code:

(require 'cl-lib)
(require 'button)
(require 'browse-url)
(require 'json)
(require 'seq)
(require 'subr-x)
(require 'transient)
(require 'diff-mode)

(defgroup stash-cli nil
  "Emacs integration for the stash-cli command line tool."
  :group 'tools)

(defcustom stash-cli-executable "stash-cli"
  "Executable name or absolute path for the stash-cli binary."
  :type 'string
  :group 'stash-cli)

(defcustom stash-cli-review-buffer-name "*stash-cli review*"
  "Buffer name used for the PR review view."
  :type 'string
  :group 'stash-cli)

(defcustom stash-cli-pr-list-buffer-name "*stash-cli prs*"
  "Buffer name used for listing open pull requests."
  :type 'string
  :group 'stash-cli)

(defcustom stash-cli-diff-buffer-name "*stash-cli diff*"
  "Buffer name used for the PR diff view."
  :type 'string
  :group 'stash-cli)

(defcustom stash-cli-created-pr-buffer-name "*stash-cli created pr*"
  "Buffer name used for displaying a newly created pull request."
  :type 'string
  :group 'stash-cli)

(defface stash-cli-review-title-face
  '((t :inherit bold :height 1.3))
  "Face for the PR title."
  :group 'stash-cli)

(defface stash-cli-review-section-face
  '((t :inherit bold :height 1.1))
  "Face for section headings."
  :group 'stash-cli)

(defface stash-cli-review-meta-face
  '((t :inherit shadow))
  "Face for secondary review metadata."
  :group 'stash-cli)

(defface stash-cli-review-blocker-face
  '((t :inherit error :weight bold))
  "Face for blocker comments."
  :group 'stash-cli)

(defface stash-cli-review-file-face
  '((t :inherit font-lock-keyword-face :weight bold))
  "Face for inline comment file headers."
  :group 'stash-cli)

(defface stash-cli-review-diff-added-face
  '((t :inherit diff-added))
  "Face for added diff lines."
  :group 'stash-cli)

(defface stash-cli-review-diff-removed-face
  '((t :inherit diff-removed))
  "Face for removed diff lines."
  :group 'stash-cli)

(defface stash-cli-review-diff-context-face
  '((t :inherit shadow))
  "Face for unchanged diff lines."
  :group 'stash-cli)

(defface stash-cli-review-diff-target-face
  '((t :inherit highlight :weight bold))
  "Face for the diff line targeted by an inline comment."
  :group 'stash-cli)

(cl-defstruct stash-cli-command-result
  command
  exit-code
  stdout
  stderr)

(define-error 'stash-cli-command-error "stash-cli command failed")

(defvar-local stash-cli--review-command-args nil
  "The stash-cli arguments used to populate the current review buffer.")

(defvar-local stash-cli--review-data nil
  "The decoded PR review payload for the current review buffer.")

(defvar-local stash-cli--comment-points nil
  "Buffer positions for top-level review comments in display order.")

(defun stash-cli--format-command (command)
  "Return COMMAND as a shell-ish string for display."
  (mapconcat #'shell-quote-argument command " "))

(defun stash-cli--run (&rest args)
  "Run stash-cli synchronously with ARGS and return a command result struct."
  (unless (executable-find stash-cli-executable)
    (user-error "Could not find `%s' in exec-path" stash-cli-executable))
  (let* ((command (cons stash-cli-executable args))
         (stdout-buffer (generate-new-buffer " *stash-cli-stdout*"))
         (stderr-buffer (generate-new-buffer " *stash-cli-stderr*")))
    (unwind-protect
        (let ((process
               (make-process
                :name "stash-cli"
                :buffer stdout-buffer
                :command command
                :stderr stderr-buffer
                :noquery t
                :connection-type 'pipe)))
          ;; Prevent sentinel messages from polluting the output buffers.
          (set-process-sentinel process #'ignore)
          (when-let ((stderr-proc (get-buffer-process stderr-buffer)))
            (set-process-sentinel stderr-proc #'ignore))
          (while (process-live-p process)
            (accept-process-output process 0.1))
          (make-stash-cli-command-result
           :command command
           :exit-code (process-exit-status process)
           :stdout (with-current-buffer stdout-buffer (buffer-string))
           :stderr (with-current-buffer stderr-buffer (buffer-string))))
      (kill-buffer stdout-buffer)
      (kill-buffer stderr-buffer))))

(defun stash-cli--ensure-success (result)
  "Signal an error when RESULT represents a failed stash-cli command."
  (unless (zerop (stash-cli-command-result-exit-code result))
    (signal
     'stash-cli-command-error
     (list
      (format
       "%s failed with exit code %s: %s"
       (stash-cli--format-command (stash-cli-command-result-command result))
       (stash-cli-command-result-exit-code result)
       (string-trim (or (stash-cli-command-result-stderr result) "")))
      result)))
  result)

(defun stash-cli--run-json (&rest args)
  "Run stash-cli with ARGS and parse stdout as JSON."
  (let* ((result (apply #'stash-cli--run args))
         (stdout nil))
    (stash-cli--ensure-success result)
    (setq stdout (string-trim (stash-cli-command-result-stdout result)))
    (when (string-empty-p stdout)
      (signal
       'stash-cli-command-error
       (list
        (format
         "%s produced no JSON output"
         (stash-cli--format-command (stash-cli-command-result-command result)))
        result)))
    (condition-case err
        (json-parse-string stdout
                           :object-type 'alist
                           :array-type 'list
                           :false-object nil
                           :null-object nil)
      (json-parse-error
       (signal
        'stash-cli-command-error
        (list
         (format
          "Failed to parse JSON from %s: %s"
          (stash-cli--format-command (stash-cli-command-result-command result))
          (error-message-string err))
         result))))))

(defun stash-cli--optional-arg (args option value)
  "Append OPTION VALUE to ARGS when VALUE is present."
  (if (and value (not (string-empty-p value)))
      (append args (list option value))
    args))

(defun stash-cli--run-async (callback &rest args)
  "Run stash-cli with ARGS asynchronously.
CALLBACK is called with a `stash-cli-command-result' when the process exits."
  (unless (executable-find stash-cli-executable)
    (user-error "Could not find `%s' in exec-path" stash-cli-executable))
  (let* ((command (cons stash-cli-executable args))
         (stdout-buffer (generate-new-buffer " *stash-cli-stdout*"))
         (stderr-buffer (generate-new-buffer " *stash-cli-stderr*")))
    (let ((process
           (make-process
            :name "stash-cli"
            :buffer stdout-buffer
            :command command
            :stderr stderr-buffer
            :noquery t
            :connection-type 'pipe
            :sentinel
            (lambda (process _event)
              (when (memq (process-status process) '(exit signal))
                (unwind-protect
                    (let ((result
                           (make-stash-cli-command-result
                            :command command
                            :exit-code (process-exit-status process)
                            :stdout (with-current-buffer stdout-buffer
                                      (buffer-string))
                            :stderr (with-current-buffer stderr-buffer
                                      (buffer-string)))))
                      (funcall callback result))
                  (kill-buffer stdout-buffer)
                  (kill-buffer stderr-buffer)))))))
      ;; Prevent the stderr pipe sentinel from polluting its buffer.
      (when-let ((stderr-proc (get-buffer-process stderr-buffer)))
        (set-process-sentinel stderr-proc #'ignore))
      process)))

(defun stash-cli--run-json-async (callback &rest args)
  "Run stash-cli with ARGS asynchronously; parse JSON and call CALLBACK with the result.
On error, signals via `message'."
  (apply #'stash-cli--run-async
         (lambda (result)
           (condition-case err
               (progn
                 (stash-cli--ensure-success result)
                 (let* ((stdout (string-trim
                                 (stash-cli-command-result-stdout result)))
                        (data (json-parse-string
                               stdout
                               :object-type 'alist
                               :array-type 'list
                               :false-object nil
                               :null-object nil)))
                   (funcall callback data)))
             (stash-cli-command-error
              (message "stash-cli error: %s" (cadr err)))))
         args))

(defun stash-cli--insert-heading (title)
  "Insert TITLE as a section heading."
  (insert (propertize title 'face 'stash-cli-review-section-face) "\n"))

(defun stash-cli--insert-action-button (label action &optional help)
  "Insert a clickable LABEL that runs ACTION."
  (insert-text-button
   label
   'action action
   'follow-link t
   'help-echo (or help label))
  (insert "  "))

(defun stash-cli--group-inline-comments (inline-comments)
  "Group INLINE-COMMENTS by file path."
  (let (groups)
    (dolist (entry inline-comments)
      (let* ((path (or (alist-get 'path entry) "<unknown file>"))
             (cell (assoc path groups)))
        (if cell
            (setcdr cell (append (cdr cell) (list entry)))
          (push (cons path (list entry)) groups))))
    (sort
     (mapcar
      (lambda (cell)
        (cons
         (car cell)
         (sort
          (copy-sequence (cdr cell))
          (lambda (left right)
            (< (or (alist-get 'line left) 0)
               (or (alist-get 'line right) 0))))))
      groups)
     (lambda (left right)
       (string-lessp (car left) (car right))))))

(defun stash-cli--comment-label (comment)
  "Return a single-line header for COMMENT."
  (let* ((author (or (alist-get 'author comment) "Unknown"))
         (created (alist-get 'created_date comment))
         (severity (alist-get 'severity comment))
         (state (alist-get 'state comment))
         (parts (list author)))
    (when (and created (not (string-empty-p created)))
      (setq parts (append parts (list (format "(%s)" created)))))
    (when (and severity (not (member severity '("" "NORMAL"))))
      (setq parts (append parts (list (format "[%s]" severity)))))
    (when (and state (not (string-empty-p state)))
      (setq parts (append parts (list (format "(%s)" state)))))
    (string-join parts " ")))

(defun stash-cli--diff-line-face (prefix is-target)
  "Return the face for diff line PREFIX.
When IS-TARGET is non-nil, highlight the target line."
  (cond
   (is-target 'stash-cli-review-diff-target-face)
   ((equal prefix "+") 'stash-cli-review-diff-added-face)
   ((equal prefix "-") 'stash-cli-review-diff-removed-face)
   (t 'stash-cli-review-diff-context-face)))

(defun stash-cli--insert-diff-snippet (snippet)
  "Insert SNIPPET into the current buffer."
  (stash-cli--insert-heading "Diff context")
  (if snippet
      (dolist (line snippet)
        (let* ((line-number (alist-get 'line_number line))
               (prefix (or (alist-get 'prefix line) " "))
               (code (or (alist-get 'code line) ""))
               (is-target (alist-get 'is_target line))
               (marker (if is-target ">>" "  "))
               (num-str (if line-number
                            (format "%5s" line-number)
                          "     ")))
          (insert
           (propertize
            (format "%s %s %s %s\n" marker num-str prefix code)
            'face (stash-cli--diff-line-face prefix is-target)))))
    (insert (propertize "  No diff context available.\n"
                        'face 'stash-cli-review-meta-face))))

(defun stash-cli--insert-comment (comment depth)
  "Insert COMMENT and its replies at DEPTH indentation."
  (let* ((indent (make-string (* depth 2) ?\s))
         (comment-id (alist-get 'id comment))
         (text (or (alist-get 'text comment) ""))
         (severity (alist-get 'severity comment))
         (face (if (equal severity "BLOCKER")
                   'stash-cli-review-blocker-face
                 'default))
         (start (point)))
    (push start stash-cli--comment-points)
    (insert indent)
    (let ((label-start (point)))
      (insert (propertize (stash-cli--comment-label comment) 'face face))
      (when comment-id
        (put-text-property label-start (point)
                           'stash-cli-comment-id comment-id)))
    (insert "\n")
    (unless (string-empty-p text)
      (insert indent "  " text "\n"))
    (dolist (reply (alist-get 'replies comment))
      (stash-cli--insert-comment reply (1+ depth)))))

(defun stash-cli--insert-reviewers (reviewers)
  "Insert REVIEWERS into the current buffer."
  (stash-cli--insert-heading "Reviewers")
  (if reviewers
      (dolist (reviewer reviewers)
        (insert
         (format
          "- %s [%s]\n"
          (or (alist-get 'display_name reviewer)
              (alist-get 'username reviewer)
              "Unknown reviewer")
           (or (alist-get 'status reviewer) "UNKNOWN"))))
    (insert "- No reviewers\n"))
  (insert "\n"))

(defun stash-cli--visit-file-button (button)
  "Open the file referenced by BUTTON."
  (stash-cli-review-visit-source (button-get button 'stash-cli-location)))

(defun stash-cli--browse-diff-button (button)
  "Open the diff URL referenced by BUTTON."
  (browse-url (button-get button 'stash-cli-url)))

(defun stash-cli--insert-file-header (path entries)
  "Insert the file header for PATH and ENTRIES."
  (let* ((location (list path (alist-get 'line (car entries))))
         (diff-url (alist-get 'diff_url (car entries))))
    (insert (propertize "File: " 'face 'stash-cli-review-meta-face))
    (insert-text-button
     path
     'action #'stash-cli--visit-file-button
     'follow-link t
     'face 'stash-cli-review-file-face
     'stash-cli-location location
     'help-echo "Visit the local file for this inline comment")
    (insert
     (propertize
      (format " (%d comment%s)\n"
              (length entries)
              (if (= (length entries) 1) "" "s"))
      'face 'stash-cli-review-meta-face))
    (when diff-url
      (insert "  ")
      (insert-text-button
       "[browse diff]"
       'action #'stash-cli--browse-diff-button
       'follow-link t
       'stash-cli-url diff-url
       'help-echo "Open this diff in a browser")
      (insert "\n"))))

(defun stash-cli--insert-inline-entry (entry)
  "Insert one inline comment ENTRY."
  (insert
   (propertize
    (format "Line %s [%s]\n"
            (or (alist-get 'line entry) "?")
            (or (alist-get 'line_type entry) "UNKNOWN"))
    'face 'stash-cli-review-meta-face))
  (stash-cli--insert-diff-snippet (alist-get 'diff_snippet entry))
  (stash-cli--insert-comment (alist-get 'comment entry) 1)
  (insert "\n"))

(defun stash-cli--insert-action-bar ()
  "Insert the review action bar."
  (stash-cli--insert-action-button "[Refresh]" (lambda (_button) (stash-cli-review-refresh))
                                   "Refresh this PR review")
  (stash-cli--insert-action-button "[Next comment]" (lambda (_button) (stash-cli-review-next-comment))
                                   "Jump to the next comment")
  (stash-cli--insert-action-button "[Previous comment]" (lambda (_button) (stash-cli-review-previous-comment))
                                   "Jump to the previous comment")
  (stash-cli--insert-action-button "[Browse PR]" (lambda (_button) (stash-cli-review-browse))
                                   "Open the PR in a browser")
  (insert "\n\n"))

(defun stash-cli--render-review-buffer (data)
  "Render pull request review DATA into the current buffer."
  (let* ((inhibit-read-only t)
         (comments (alist-get 'comments data))
         (general-comments (alist-get 'general comments))
         (inline-comments (alist-get 'inline comments)))
    (erase-buffer)
    (setq-local stash-cli--review-data data)
    (setq-local stash-cli--comment-points nil)
    (insert
     (propertize
      (format "PR #%s: %s\n"
              (or (alist-get 'id data) "?")
              (or (alist-get 'title data) ""))
      'face 'stash-cli-review-title-face))
    (stash-cli--insert-action-bar)
    (insert
     (format "State: %s\nAuthor: %s\nBranches: %s -> %s\n"
             (or (alist-get 'state data) "UNKNOWN")
             (or (alist-get 'author data) "Unknown")
             (or (alist-get 'source_branch data) "?")
             (or (alist-get 'target_branch data) "?")))
    (when-let ((url (alist-get 'url data)))
      (unless (string-empty-p url)
        (insert "URL: ")
        (insert-text-button
         url
         'action (lambda (_button) (browse-url url))
         'follow-link t
         'help-echo "Open this PR in a browser")
        (insert "\n")))
    (when-let ((description (alist-get 'description data)))
      (unless (string-empty-p description)
        (insert "\n")
        (stash-cli--insert-heading "Description")
        (insert description "\n")))
    (insert "\n")
    (stash-cli--insert-reviewers (alist-get 'reviewers data))
    (stash-cli--insert-heading
     (format "General comments (%d)" (length general-comments)))
    (if general-comments
        (dolist (comment general-comments)
          (stash-cli--insert-comment comment 0))
      (insert "- No general comments\n"))
    (insert "\n")
    (stash-cli--insert-heading
     (format "Inline comments (%d)" (length inline-comments)))
    (if inline-comments
        (dolist (group (stash-cli--group-inline-comments inline-comments))
          (stash-cli--insert-file-header (car group) (cdr group))
          (dolist (entry (cdr group))
            (stash-cli--insert-inline-entry entry)))
      (insert "- No inline comments\n"))
    (setq-local stash-cli--comment-points (nreverse stash-cli--comment-points))
    (goto-char (point-min))))

(defun stash-cli--render-pr-list-buffer (payload)
  "Render list-prs PAYLOAD into the current `tabulated-list-mode' buffer."
  (let ((pull-requests (alist-get 'pull_requests payload)))
    (setq tabulated-list-entries
          (mapcar
           (lambda (pr)
             (let* ((id (format "%s" (or (alist-get 'id pr) "?")))
                    (title (or (alist-get 'title pr) ""))
                    (author (or (alist-get 'author pr) "Unknown"))
                    (branches (format "%s → %s"
                                      (or (alist-get 'source_branch pr) "?")
                                      (or (alist-get 'target_branch pr) "?")))
                    (reviewers
                     (mapconcat
                      (lambda (r)
                        (format "%s[%s]"
                                (or (alist-get 'display_name r)
                                    (alist-get 'username r) "?")
                                (or (alist-get 'status r) "?")))
                      (alist-get 'reviewers pr)
                      " "))
                    (url (or (alist-get 'url pr) "")))
               (list url (vector id title author branches reviewers))))
           pull-requests))
    (tabulated-list-print t)))

(defun stash-cli--show-review (args)
  "Run `stash-cli pr' with ARGS and display the review buffer."
  (let ((data (apply #'stash-cli--run-json args))
        (buffer (get-buffer-create stash-cli-review-buffer-name)))
    (with-current-buffer buffer
      (stash-cli-review-mode)
      (setq stash-cli--review-command-args args)
      (stash-cli--render-review-buffer data))
    (pop-to-buffer buffer)
    buffer))

(defun stash-cli--nearest-next-comment (point)
  "Return the next comment position after POINT."
  (cl-find-if (lambda (pos) (> pos point)) stash-cli--comment-points))

(defun stash-cli--nearest-previous-comment (point)
  "Return the previous comment position before POINT."
  (car (last (seq-filter (lambda (pos) (< pos point)) stash-cli--comment-points))))

(define-derived-mode stash-cli-review-mode special-mode "Stash-Review"
  "Major mode for viewing stash-cli pull request reviews."
  (setq-local revert-buffer-function #'stash-cli-review-refresh)
  (setq-local truncate-lines t))

(defun stash-cli-review-next-comment ()
  "Jump to the next comment in the current review buffer."
  (interactive)
  (let ((next (stash-cli--nearest-next-comment (point))))
    (if next
        (goto-char next)
      (message "No later comments"))))

(defun stash-cli-review-previous-comment ()
  "Jump to the previous comment in the current review buffer."
  (interactive)
  (let ((prev (stash-cli--nearest-previous-comment (point))))
    (goto-char (or prev (point-min)))))

(defun stash-cli-review-browse ()
  "Open the current pull request in a browser."
  (interactive)
  (let ((url (alist-get 'url stash-cli--review-data)))
    (unless (and url (not (string-empty-p url)))
      (user-error "This review buffer does not have a PR URL"))
    (browse-url url)))

(defun stash-cli-review-visit-source (&optional location)
  "Visit the source LOCATION for the current inline comment.
LOCATION is a list of (PATH LINE)."
  (interactive)
  (let* ((location
          (or location
              (when-let ((button (button-at (point))))
                (button-get button 'stash-cli-location))))
         (path (car-safe location))
         (line (cadr location)))
    (unless path
      (user-error "No source location at point"))
    (unless (file-exists-p path)
      (user-error "Cannot find %s relative to %s" path default-directory))
    (find-file-other-window path)
    (when line
      (goto-char (point-min))
      (forward-line (1- line)))))

(define-key stash-cli-review-mode-map (kbd "g") #'stash-cli-review-refresh)
(define-key stash-cli-review-mode-map (kbd "n") #'stash-cli-review-next-comment)
(define-key stash-cli-review-mode-map (kbd "p") #'stash-cli-review-previous-comment)
(define-key stash-cli-review-mode-map (kbd "b") #'stash-cli-review-browse)
(define-key stash-cli-review-mode-map (kbd "v") #'stash-cli-review-visit-source)
(define-key stash-cli-review-mode-map (kbd "RET") #'push-button)
(define-key stash-cli-review-mode-map (kbd "r") #'stash-cli-review-reply)
(define-key stash-cli-review-mode-map (kbd "c") #'stash-cli-review-comment)
(define-key stash-cli-review-mode-map (kbd "a") #'stash-cli-review-approve)
(define-key stash-cli-review-mode-map (kbd "A") #'stash-cli-review-needs-work)
(define-key stash-cli-review-mode-map (kbd "d") #'stash-cli-review-diff)
(define-key stash-cli-review-mode-map (kbd "?") #'stash-cli-review-dispatch)

(with-eval-after-load 'evil
  (evil-define-key* 'normal stash-cli-review-mode-map
    "g"   #'stash-cli-review-refresh
    "n"   #'stash-cli-review-next-comment
    "p"   #'stash-cli-review-previous-comment
    "b"   #'stash-cli-review-browse
    "v"   #'stash-cli-review-visit-source
    "r"   #'stash-cli-review-reply
    "c"   #'stash-cli-review-comment
    "a"   #'stash-cli-review-approve
    "A"   #'stash-cli-review-needs-work
    "d"   #'stash-cli-review-diff
    "?"   #'stash-cli-review-dispatch
    (kbd "RET") #'push-button))

(defun stash-cli-review-current-branch ()
  "Show the current branch pull request review in Emacs."
  (interactive)
  (stash-cli--show-review '("pr" "--format" "json")))

(defun stash-cli-review-branch (branch)
  "Show the pull request review for BRANCH."
  (interactive "sBranch: ")
  (stash-cli--show-review
   (list "pr" "--format" "json" "--branch" branch)))

(defun stash-cli-review-url (url)
  "Show the pull request review for URL."
  (interactive "sPR URL: ")
  (stash-cli--show-review
   (list "pr" "--format" "json" "--url" url)))

(defun stash-cli-review-refresh (&rest _ignore)
  "Refresh the current stash-cli review buffer."
  (interactive)
  (unless stash-cli--review-command-args
    (user-error "This buffer was not populated by stash-cli"))
  (stash-cli--show-review stash-cli--review-command-args))

(defun stash-cli-list-prs ()
  "List open pull requests for the current repository."
  (interactive)
  (let ((buffer (get-buffer-create stash-cli-pr-list-buffer-name)))
    (with-current-buffer buffer
      (stash-cli-pr-list-mode)
      (stash-cli--run-json-async
       (lambda (payload)
         (with-current-buffer buffer
           (stash-cli--render-pr-list-buffer payload)))
       "list-prs" "--format" "json"))
    (pop-to-buffer buffer)))

(define-derived-mode stash-cli-pr-list-mode tabulated-list-mode "Stash-PRs"
  "Major mode for listing open pull requests."
  (setq tabulated-list-format
        [("ID" 6 t)
         ("Title" 45 t)
         ("Author" 18 t)
         ("Branches" 30 t)
         ("Reviewers" 30 t)])
  (tabulated-list-init-header))

(defun stash-cli-pr-list-open-review ()
  "Open the review buffer for the PR at point."
  (interactive)
  (let ((url (tabulated-list-get-id)))
    (unless (and url (not (string-empty-p url)))
      (user-error "No PR URL at point"))
    (stash-cli-review-url url)))

(defun stash-cli-pr-list-browse ()
  "Open the PR at point in a browser."
  (interactive)
  (let ((url (tabulated-list-get-id)))
    (unless (and url (not (string-empty-p url)))
      (user-error "No PR URL at point"))
    (browse-url url)))

(defun stash-cli-pr-list-refresh ()
  "Refresh the PR list."
  (interactive)
  (stash-cli--run-json-async
   (lambda (payload)
     (when-let ((buffer (get-buffer stash-cli-pr-list-buffer-name)))
       (with-current-buffer buffer
         (stash-cli--render-pr-list-buffer payload))))
   "list-prs" "--format" "json")
  (message "Refreshing PR list..."))

(define-key stash-cli-pr-list-mode-map (kbd "RET") #'stash-cli-pr-list-open-review)
(define-key stash-cli-pr-list-mode-map (kbd "g") #'stash-cli-pr-list-refresh)
(define-key stash-cli-pr-list-mode-map (kbd "b") #'stash-cli-pr-list-browse)
(define-key stash-cli-pr-list-mode-map (kbd "c") #'stash-cli-create-pr)
(define-key stash-cli-pr-list-mode-map (kbd "?") #'stash-cli-dispatch)

(with-eval-after-load 'evil
  (evil-define-key* 'normal stash-cli-pr-list-mode-map
    "g"   #'stash-cli-pr-list-refresh
    "b"   #'stash-cli-pr-list-browse
    "c"   #'stash-cli-create-pr
    "?"   #'stash-cli-dispatch
    (kbd "RET") #'stash-cli-pr-list-open-review))

(defun stash-cli--render-created-pr-buffer (payload)
  "Render the newly created PR PAYLOAD into the current buffer."
  (let ((inhibit-read-only t)
        (id (or (alist-get 'id payload) "?"))
        (title (or (alist-get 'title payload) ""))
        (url (alist-get 'url payload))
        (source (or (alist-get 'source_branch payload) "?"))
        (target (or (alist-get 'target_branch payload) "?"))
        (author (or (alist-get 'author payload) ""))
        (state (or (alist-get 'state payload) ""))
        (description (or (alist-get 'description payload) "")))
    (erase-buffer)
    (insert
     (propertize
      (format "✓ Created PR #%s: %s\n\n" id title)
      'face 'stash-cli-review-title-face))
    (when url
      (stash-cli--insert-action-button
       "[Browse PR]"
       (lambda (_button) (browse-url url))
       "Open this PR in a browser")
      (insert "\n\n"))
    (unless (string-empty-p author)
      (insert (format "Author:   %s\n" author)))
    (insert (format "Branches: %s → %s\n" source target))
    (unless (string-empty-p state)
      (insert (format "State:    %s\n" state)))
    (when (and url (not (string-empty-p url)))
      (insert "URL:      ")
      (insert-text-button
       url
       'action (lambda (_button) (browse-url url))
       'follow-link t
       'help-echo "Open this PR in a browser")
      (insert "\n"))
    (when (and description (not (string-empty-p description)))
      (insert "\n")
      (stash-cli--insert-heading "Description")
      (insert description "\n"))
    (goto-char (point-min))))

(define-derived-mode stash-cli-created-pr-mode special-mode "Stash-Created-PR"
  "Major mode for viewing a newly created pull request."
  (setq-local truncate-lines t))

(defun stash-cli-create-pr (title description target &optional source reviewers)
  "Create a pull request with TITLE and DESCRIPTION.

When SOURCE, TARGET, or REVIEWERS are non-empty strings they are passed
through to the CLI."
  (interactive
   (list
    (read-string "PR Title: ")
    (read-string "PR Description: ")
    (read-string "Target branch (blank = CLI default): ")
    (read-string "Source branch (blank = current): ")
    (read-string "Reviewers (comma-separated, blank = none): ")))
  (let ((args (list "create-pr"
                    "--format" "json"
                    "--title" title
                    "--description" description)))
    (setq args (stash-cli--optional-arg args "--source" source))
    (setq args (stash-cli--optional-arg args "--target" target))
    (setq args (stash-cli--optional-arg args "--reviewers" reviewers))
    (let* ((payload (apply #'stash-cli--run-json args))
           (buffer (get-buffer-create stash-cli-created-pr-buffer-name)))
      (with-current-buffer buffer
        (stash-cli-created-pr-mode)
        (stash-cli--render-created-pr-buffer payload))
      (pop-to-buffer buffer)
      (message "Created PR #%s" (or (alist-get 'id payload) "?")))))

(defun stash-cli-pr-comment (text &optional url)
  "Post TEXT as a general pull request comment.

When URL is provided, target that PR instead of auto-detecting from the
current branch."
  (interactive
   (list
    (read-string "Comment text: ")
    (read-string "PR URL (blank = current branch): ")))
  (let ((args (list "pr-comment" "--format" "json" text)))
    (setq args (stash-cli--optional-arg args "--url" url))
    (let ((payload (apply #'stash-cli--run-json args)))
      (message
       "Posted comment %s on PR #%s"
       (or (alist-get 'comment_id payload) "?")
       (or (alist-get 'pr_id payload) "?")))))

(defun stash-cli-pr-add-reviewers (usernames &optional url)
  "Add USERNAMES to the current pull request.

USERNAMES is a comma-separated string.  When URL is provided, target that
PR instead of auto-detecting from the current branch."
  (interactive
   (list
    (read-string "Reviewers to add (comma-separated): ")
    (read-string "PR URL (blank = current branch): ")))
  (let ((args '("pr-add-reviewer" "--format" "json")))
    (dolist (username (split-string usernames "," t "[[:space:]\n]+"))
      (setq args (append args (list username))))
    (setq args (stash-cli--optional-arg args "--url" url))
    (let* ((payload (apply #'stash-cli--run-json args))
           (added (alist-get 'added payload)))
      (message
       "Added reviewer(s) to PR #%s: %s"
       (or (alist-get 'pr_id payload) "?")
       (if added
           (string-join added ", ")
         "none")))))

(defun stash-cli-pr-remove-reviewer (username &optional url)
  "Remove USERNAME from the current pull request.

When URL is provided, target that PR instead of auto-detecting from the
current branch."
  (interactive
   (list
    (read-string "Reviewer to remove: ")
    (read-string "PR URL (blank = current branch): ")))
  (let ((args (list "pr-remove-reviewer" "--format" "json" username)))
    (setq args (stash-cli--optional-arg args "--url" url))
    (let ((payload (apply #'stash-cli--run-json args)))
      (message
       "Removed reviewer %s from PR #%s"
       (or (alist-get 'username payload) username)
       (or (alist-get 'pr_id payload) "?")))))

;; ---------------------------------------------------------------------------
;; Review workflow: reply, approve, needs-work, comment, diff
;; ---------------------------------------------------------------------------

(defun stash-cli--review-url ()
  "Return the PR URL from the current review buffer data."
  (let ((url (alist-get 'url stash-cli--review-data)))
    (unless (and url (not (string-empty-p url)))
      (user-error "This review buffer does not have a PR URL"))
    url))

(defun stash-cli--comment-id-at-point ()
  "Return the comment ID for the nearest comment at or before point."
  (or (get-text-property (point) 'stash-cli-comment-id)
      (save-excursion
        (when-let ((prev (stash-cli--nearest-previous-comment (1+ (point)))))
          (get-text-property prev 'stash-cli-comment-id)))))

(defun stash-cli-review-reply ()
  "Reply to the comment at point."
  (interactive)
  (let ((comment-id (stash-cli--comment-id-at-point)))
    (unless comment-id
      (user-error "No comment at point to reply to"))
    (let* ((text (read-string (format "Reply to comment #%d: " comment-id)))
           (url (stash-cli--review-url))
           (args (list "pr-reply" "--format" "json"
                       (number-to-string comment-id)
                       text "--url" url)))
      (apply #'stash-cli--run-json args)
      (message "Reply posted to comment #%d" comment-id)
      (stash-cli-review-refresh))))

(defun stash-cli-review-comment ()
  "Post a general comment on the current PR."
  (interactive)
  (let* ((text (read-string "Comment: "))
         (url (stash-cli--review-url)))
    (stash-cli-pr-comment text url)
    (stash-cli-review-refresh)))

(defun stash-cli--review-set-status (status)
  "Set review STATUS (APPROVED or NEEDS_WORK) on the current PR."
  (let* ((url (stash-cli--review-url))
         (args (list "pr-approve" "--format" "json" status "--url" url)))
    (apply #'stash-cli--run-json args)
    (message "PR marked as %s" status)
    (stash-cli-review-refresh)))

(defun stash-cli-review-approve ()
  "Approve the current PR."
  (interactive)
  (stash-cli--review-set-status "APPROVED"))

(defun stash-cli-review-needs-work ()
  "Mark the current PR as needs work."
  (interactive)
  (stash-cli--review-set-status "NEEDS_WORK"))

;; ---------------------------------------------------------------------------
;; Diff viewer
;; ---------------------------------------------------------------------------

(defvar-local stash-cli--diff-pr-url nil
  "The PR URL associated with the current diff buffer.")

(defun stash-cli-pr-diff (&optional url)
  "Show the full diff for the current branch PR, or for URL."
  (interactive
   (list (read-string "PR URL (blank = current branch): ")))
  (let ((args (list "pr-diff" "--format" "json")))
    (setq args (stash-cli--optional-arg args "--url" url))
    (let* ((payload (apply #'stash-cli--run-json args))
           (diff-text (or (alist-get 'diff payload) ""))
           (pr-url (or url ""))
           (buffer (get-buffer-create stash-cli-diff-buffer-name)))
      (with-current-buffer buffer
        (let ((inhibit-read-only t))
          (erase-buffer)
          (insert diff-text)
          (goto-char (point-min)))
        (diff-mode)
        (setq-local stash-cli--diff-pr-url pr-url)
        (setq buffer-read-only t))
      (pop-to-buffer buffer)
      buffer)))

(defun stash-cli-review-diff ()
  "Show the full diff for the PR in the current review buffer."
  (interactive)
  (stash-cli-pr-diff (stash-cli--review-url)))

(defun stash-cli-diff-inline-comment ()
  "Post an inline comment on the diff line at point."
  (interactive)
  (unless stash-cli--diff-pr-url
    (user-error "Not in a stash-cli diff buffer"))
  (let* ((file (diff-find-file-name t))
         (line-info (diff-find-source-location))
         (line (car line-info))
         (text (read-string (format "Comment on %s:%d: " file line))))
    (let ((args (list "pr-inline-comment" "--format" "json"
                      file (number-to-string line) text)))
      (setq args (stash-cli--optional-arg args "--url" stash-cli--diff-pr-url))
      (apply #'stash-cli--run-json args)
      (message "Inline comment posted on %s:%d" file line))))

;; ---------------------------------------------------------------------------
;; Transient dispatch menus
;; ---------------------------------------------------------------------------

(transient-define-prefix stash-cli-dispatch ()
  "Stash-CLI command dispatch."
  ["Pull Requests"
   ("l" "List PRs" stash-cli-list-prs)
   ("r" "Review current branch" stash-cli-review-current-branch)
   ("u" "Review PR by URL" stash-cli-review-url)
   ("d" "Show PR diff" stash-cli-pr-diff)
   ("c" "Create PR" stash-cli-create-pr)])

(transient-define-prefix stash-cli-review-dispatch ()
  "Actions for the current PR review."
  ["Navigate"
   ("n" "Next comment" stash-cli-review-next-comment)
   ("p" "Previous comment" stash-cli-review-previous-comment)
   ("v" "Visit source" stash-cli-review-visit-source)]
  ["Actions"
   ("r" "Reply to comment" stash-cli-review-reply)
   ("c" "Post comment" stash-cli-review-comment)
   ("a" "Approve" stash-cli-review-approve)
   ("A" "Needs work" stash-cli-review-needs-work)
   ("d" "Show diff" stash-cli-review-diff)]
  ["Other"
   ("g" "Refresh" stash-cli-review-refresh)
   ("b" "Browse PR" stash-cli-review-browse)])

(provide 'stash-cli)

;;; stash-cli.el ends here
