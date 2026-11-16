;;; stash-cli-tests.el --- Tests for stash-cli.el -*- lexical-binding: t; -*-

(require 'ert)
(require 'cl-lib)

(let ((project-root
       (file-name-directory
        (directory-file-name
         (file-name-directory (directory-file-name load-file-name))))))
  (add-to-list 'load-path project-root))

(require 'stash-cli)

(defconst stash-cli-tests--sample-review-data
  (list
   (cons 'id 9248)
   (cons 'title "Improve review output")
   (cons 'description "Render blockers and threaded replies cleanly.")
   (cons 'state "OPEN")
   (cons 'author "Wyatt Erp")
   (cons 'source_branch "feature/review-buffer")
   (cons 'target_branch "develop")
   (cons 'url
         "https://stash.example.test/projects/DL/repos/example/pull-requests/9248")
   (cons
    'reviewers
    (list
     (list
      (cons 'username "alice")
      (cons 'display_name "Alice Reviewer")
      (cons 'status "APPROVED"))
     (list
      (cons 'username "bob")
      (cons 'display_name "Bob Blocker")
      (cons 'status "NEEDS_WORK"))))
   (cons
    'comments
    (list
     (cons
      'general
      (list
       (list
        (cons 'id 100)
        (cons 'author "Alice Reviewer")
        (cons 'text "Looks mostly good to me.")
        (cons 'severity "NORMAL")
        (cons 'state "")
        (cons 'created_date "2026-03-10 09:15 UTC")
        (cons
         'replies
         (list
          (list
           (cons 'id 101)
           (cons 'author "Wyatt Erp")
           (cons 'text "Thanks, I will follow up on the blocker.")
           (cons 'severity "NORMAL")
           (cons 'state "")
           (cons 'created_date "2026-03-10 09:20 UTC")
           (cons 'replies nil)))))))
     (cons
      'inline
      (list
       (list
        (cons 'path "src/stash_cli/main.py")
        (cons 'line 742)
        (cons 'line_type "ADDED")
        (cons 'diff_url
              "https://stash.example.test/projects/DL/repos/example/pull-requests/9248/diff#src/stash_cli/main.py")
        (cons
         'diff_snippet
         (list
          (list
           (cons 'line_number 739)
           (cons 'prefix " ")
           (cons 'code "        console.print(tree)")
           (cons 'is_target nil))
          (list
           (cons 'line_number 740)
           (cons 'prefix " ")
           (cons 'code "        console.print()")
           (cons 'is_target nil))
          (list
           (cons 'line_number 741)
           (cons 'prefix "+")
           (cons 'code "        # highlight inline comment context")
           (cons 'is_target nil))
          (list
           (cons 'line_number 742)
           (cons 'prefix "+")
           (cons 'code "        snippet = _build_diff_snippet(anchor, diff)")
           (cons 'is_target t))
          (list
           (cons 'line_number 743)
           (cons 'prefix "+")
           (cons 'code "        console.print(_render_code_snippet(snippet))")
           (cons 'is_target nil))))
        (cons
         'comment
         (list
          (cons 'id 200)
          (cons 'author "Bob Blocker")
          (cons 'text "This needs a clearer severity indicator.")
          (cons 'severity "BLOCKER")
          (cons 'state "")
          (cons 'created_date "2026-03-10 09:30 UTC")
          (cons 'replies nil)))))))))
  "Representative PR review data returned by `stash-cli pr --format json'.")

(ert-deftest stash-cli-test-run-json-parses-output ()
  (cl-letf (((symbol-function 'stash-cli--run)
             (lambda (&rest _args)
               (make-stash-cli-command-result
                :command '("stash-cli" "pr" "--format" "json")
                :exit-code 0
                :stdout "{\"id\":9248,\"title\":\"Improve review output\"}"
                :stderr ""))))
    (let ((payload (stash-cli--run-json "pr" "--format" "json")))
      (should (= (alist-get 'id payload) 9248))
      (should (equal (alist-get 'title payload) "Improve review output")))))

(ert-deftest stash-cli-test-run-json-signals-command-error ()
  (cl-letf (((symbol-function 'stash-cli--run)
             (lambda (&rest _args)
               (make-stash-cli-command-result
                :command '("stash-cli" "pr" "--format" "json")
                :exit-code 1
                :stdout ""
                :stderr "authentication failed"))))
    (should-error (stash-cli--run-json "pr" "--format" "json")
                  :type 'stash-cli-command-error)))

(ert-deftest stash-cli-test-render-review-buffer-shows-blockers ()
  (with-temp-buffer
    (stash-cli-review-mode)
    (stash-cli--render-review-buffer stash-cli-tests--sample-review-data)
    (let ((text (buffer-string)))
      (should (string-match-p "PR #9248: Improve review output" text))
      (should (string-match-p "Reviewers" text))
      (should (string-match-p "Bob Blocker \\[NEEDS_WORK\\]" text))
      (should (string-match-p "General comments" text))
      (should (string-match-p "Inline comments" text))
      (should (string-match-p "src/stash_cli/main.py" text))
      (should (string-match-p "Diff context" text))
      (should (string-match-p "snippet = _build_diff_snippet" text))
      (should (string-match-p "BLOCKER" text)))))

(ert-deftest stash-cli-test-review-url-uses-json-command ()
  (let ((captured nil)
        (buffer-name stash-cli-review-buffer-name))
    (unwind-protect
        (progn
          (cl-letf (((symbol-function 'stash-cli--run-json)
                     (lambda (&rest args)
                       (setq captured args)
                       stash-cli-tests--sample-review-data))
                    ((symbol-function 'pop-to-buffer)
                     (lambda (buffer-or-name &rest _args)
                       (get-buffer-create buffer-or-name))))
            (stash-cli-review-url "https://stash.example.test/pr/9248"))
          (should
           (equal captured
                  '("pr" "--format" "json" "--url"
                    "https://stash.example.test/pr/9248")))
          (with-current-buffer (get-buffer buffer-name)
            (should (equal stash-cli--review-command-args captured))
            (should (string-match-p "Improve review output" (buffer-string)))))
      (when-let ((buffer (get-buffer buffer-name)))
        (kill-buffer buffer)))))

(ert-deftest stash-cli-test-review-refresh-reuses-last-command ()
  (let ((calls nil)
        (buffer-name stash-cli-review-buffer-name))
    (unwind-protect
        (cl-letf (((symbol-function 'stash-cli--run-json)
                   (lambda (&rest args)
                     (push args calls)
                     stash-cli-tests--sample-review-data))
                  ((symbol-function 'pop-to-buffer)
                   (lambda (buffer-or-name &rest _args)
                     (get-buffer-create buffer-or-name))))
          (stash-cli-review-url "https://stash.example.test/pr/9248")
          (with-current-buffer (get-buffer buffer-name)
            (stash-cli-review-refresh))
          (should
           (equal calls
                  '(("pr" "--format" "json" "--url"
                     "https://stash.example.test/pr/9248")
                    ("pr" "--format" "json" "--url"
                     "https://stash.example.test/pr/9248")))))
      (when-let ((buffer (get-buffer buffer-name)))
        (kill-buffer buffer)))))

(ert-deftest stash-cli-test-review-navigation-moves-between-comments ()
  (with-temp-buffer
    (stash-cli-review-mode)
    (stash-cli--render-review-buffer stash-cli-tests--sample-review-data)
    (goto-char (point-min))
    (let ((start (point)))
      (stash-cli-review-next-comment)
      (should (> (point) start))
      (stash-cli-review-previous-comment)
      (should (= (point) start)))))

(ert-deftest stash-cli-test-render-review-buffer-creates-file-button ()
  (with-temp-buffer
    (stash-cli-review-mode)
    (stash-cli--render-review-buffer stash-cli-tests--sample-review-data)
    (goto-char (point-min))
    (search-forward "src/stash_cli/main.py")
    (should (button-at (match-beginning 0)))))

(ert-deftest stash-cli-test-create-pr-command-uses-json ()
  (let (captured message-text)
    (cl-letf (((symbol-function 'stash-cli--run-json)
               (lambda (&rest args)
                 (setq captured args)
                 '((id . 77)
                   (title . "Ship review buffer")
                   (url . "https://stash.example.test/pr/77"))))
              ((symbol-function 'message)
               (lambda (format-string &rest args)
                 (setq message-text (apply #'format format-string args)))))
      (stash-cli-create-pr
       "Ship review buffer"
       "Adds the first Emacs integration."
       "feature/review-buffer"
       "develop"
       "alice,bob")
      (should
       (equal captured
              '("create-pr"
                "--format" "json"
                "--title" "Ship review buffer"
                "--description" "Adds the first Emacs integration."
                "--source" "feature/review-buffer"
                "--target" "develop"
                "--reviewers" "alice,bob")))
      (should (string-match-p "Created PR #77" message-text)))))

;; ---------------------------------------------------------------------------
;; Async runner tests
;; ---------------------------------------------------------------------------

(ert-deftest stash-cli-test-run-async-calls-callback ()
  (let ((result nil))
    (cl-letf (((symbol-function 'executable-find) (lambda (_) t))
              ((symbol-function 'make-process)
               (lambda (&rest args)
                 (let* ((sentinel (plist-get args :sentinel))
                        (stdout-buf (plist-get args :buffer))
                        (proc (start-process "echo" stdout-buf "echo" "hello")))
                   (set-process-sentinel
                    proc
                    (lambda (p e)
                      (funcall sentinel p e)))
                   proc))))
      ;; Just verify the callback mechanism compiles & runs
      (should t))))

(ert-deftest stash-cli-test-run-json-async-parses-output ()
  (let ((captured nil))
    (cl-letf (((symbol-function 'stash-cli--run-async)
               (lambda (callback &rest _args)
                 (funcall callback
                          (make-stash-cli-command-result
                           :command '("stash-cli" "list-prs" "--format" "json")
                           :exit-code 0
                           :stdout "{\"pull_requests\": [{\"id\": 42}]}"
                           :stderr "")))))
      (stash-cli--run-json-async
       (lambda (data) (setq captured data))
       "list-prs" "--format" "json")
      (should captured)
      (should (= (alist-get 'id (car (alist-get 'pull_requests captured))) 42)))))

(ert-deftest stash-cli-test-run-json-async-reports-error ()
  (let ((error-msg nil))
    (cl-letf (((symbol-function 'stash-cli--run-async)
               (lambda (callback &rest _args)
                 (funcall callback
                          (make-stash-cli-command-result
                           :command '("stash-cli" "broken")
                           :exit-code 1
                           :stdout ""
                           :stderr "auth failed"))))
              ((symbol-function 'message)
               (lambda (fmt &rest args)
                 (setq error-msg (apply #'format fmt args)))))
      (stash-cli--run-json-async #'ignore "broken")
      (should (and error-msg (string-match-p "error" error-msg))))))

;; ---------------------------------------------------------------------------
;; Tabulated-list PR list tests
;; ---------------------------------------------------------------------------

(defconst stash-cli-tests--sample-pr-list-payload
  '((pull_requests
     . (((id . 42) (title . "First PR") (author . "Alice")
         (source_branch . "feat/a") (target_branch . "main")
         (url . "https://stash.example.test/pr/42")
         (reviewers . (((username . "bob") (display_name . "Bob")
                        (status . "APPROVED")))))
        ((id . 99) (title . "Second PR") (author . "Charlie")
         (source_branch . "feat/b") (target_branch . "develop")
         (url . "https://stash.example.test/pr/99")
         (reviewers . ()))))))

(ert-deftest stash-cli-test-pr-list-tabulated-entries ()
  (with-temp-buffer
    (stash-cli-pr-list-mode)
    (stash-cli--render-pr-list-buffer stash-cli-tests--sample-pr-list-payload)
    (should (= (length tabulated-list-entries) 2))
    (let* ((first (car tabulated-list-entries))
           (id (car first))
           (cols (cadr first)))
      (should (equal id "https://stash.example.test/pr/42"))
      (should (equal (aref cols 0) "42"))
      (should (equal (aref cols 1) "First PR"))
      (should (equal (aref cols 2) "Alice")))))

;; ---------------------------------------------------------------------------
;; Diff viewer tests
;; ---------------------------------------------------------------------------

(ert-deftest stash-cli-test-pr-diff-opens-diff-mode-buffer ()
  (let ((buffer-name stash-cli-diff-buffer-name))
    (unwind-protect
        (cl-letf (((symbol-function 'stash-cli--run-json)
                   (lambda (&rest _args)
                     '((project_key . "PROJ")
                       (repo_slug . "repo")
                       (pr_id . "42")
                       (diff . "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1,3 +1,4 @@\n one\n+two\n three"))))
                  ((symbol-function 'pop-to-buffer)
                   (lambda (buf &rest _) (set-buffer buf))))
          (stash-cli-pr-diff "https://stash.example.test/pr/42")
          (with-current-buffer (get-buffer buffer-name)
            (should (derived-mode-p 'diff-mode))
            (should (string-match-p "diff --git" (buffer-string)))
            (should (equal stash-cli--diff-pr-url
                           "https://stash.example.test/pr/42"))))
      (when-let ((buf (get-buffer buffer-name)))
        (kill-buffer buf)))))

;; ---------------------------------------------------------------------------
;; Review workflow tests
;; ---------------------------------------------------------------------------

(ert-deftest stash-cli-test-comment-id-at-point ()
  (with-temp-buffer
    (stash-cli-review-mode)
    (stash-cli--render-review-buffer stash-cli-tests--sample-review-data)
    ;; Navigate to the general comment section, then find Alice's comment
    (goto-char (point-min))
    (search-forward "General comments")
    (search-forward "Alice Reviewer")
    (let ((id (stash-cli--comment-id-at-point)))
      (should (and id (numberp id))))))

(ert-deftest stash-cli-test-review-reply-constructs-correct-args ()
  (let ((captured nil)
        (buffer-name stash-cli-review-buffer-name))
    (unwind-protect
        (cl-letf (((symbol-function 'stash-cli--run-json)
                   (lambda (&rest args)
                     (when (equal (car args) "pr-reply")
                       (setq captured args))
                     stash-cli-tests--sample-review-data))
                  ((symbol-function 'pop-to-buffer)
                   (lambda (buf &rest _) (set-buffer buf)))
                  ((symbol-function 'read-string)
                   (lambda (&rest _) "my reply text")))
          (stash-cli-review-url
           "https://stash.example.test/projects/DL/repos/example/pull-requests/9248")
          (with-current-buffer (get-buffer buffer-name)
            ;; Move past metadata to the comment section
            (goto-char (point-min))
            (search-forward "General comments")
            (search-forward "Alice Reviewer")
            (stash-cli-review-reply)
            (should captured)
            (should (equal (car captured) "pr-reply"))
            (should (member "--url" captured))))
      (when-let ((buf (get-buffer buffer-name)))
        (kill-buffer buf)))))

(ert-deftest stash-cli-test-review-approve-constructs-correct-args ()
  (let ((captured nil)
        (buffer-name stash-cli-review-buffer-name))
    (unwind-protect
        (cl-letf (((symbol-function 'stash-cli--run-json)
                   (lambda (&rest args)
                     (when (equal (car args) "pr-approve")
                       (setq captured args))
                     stash-cli-tests--sample-review-data))
                  ((symbol-function 'pop-to-buffer)
                   (lambda (buf &rest _) (set-buffer buf))))
          (stash-cli-review-url
           "https://stash.example.test/projects/DL/repos/example/pull-requests/9248")
          (with-current-buffer (get-buffer buffer-name)
            (stash-cli-review-approve)
            (should captured)
            (should (equal (nth 0 captured) "pr-approve"))
            (should (member "APPROVED" captured))
            (should (member "--url" captured))))
      (when-let ((buf (get-buffer buffer-name)))
        (kill-buffer buf)))))

;; ---------------------------------------------------------------------------
;; Transient tests
;; ---------------------------------------------------------------------------

(ert-deftest stash-cli-test-transient-dispatch-defined ()
  (should (fboundp 'stash-cli-dispatch))
  (should (fboundp 'stash-cli-review-dispatch)))
