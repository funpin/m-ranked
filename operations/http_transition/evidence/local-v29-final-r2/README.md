# Final V29 HTTP proof with the unchanged root JAR

PASS: 700 real FastAPI/Spring requests, zero failures, p95 42.301 ms over
29.836822 seconds. Seven failed admission gates, four real Java admin commands,
and ten original input receipts were verified. S-final R66 advanced to a new
S-final R111; its exact completed-batch repeat wrote zero rows at unchanged
R111 with the full identity-history hash unchanged.

The supplied JAR was copied byte-for-byte into a private immutable file. Both
original and executed bytes retained SHA-256
`db588efb5e8c33d8300a44d32b3e64725ece1b6dcb61a036544b466ab29f69aa`.
The actual schema was installed by Flyway through frozen V29. The unchanged
`reverse-http.json` passed the same JQ predicate used by production preflight;
`protocol-validation.json` records the original input/predicate hashes.

Reproduction used:

```sh
rtk proxy env JAVA_HOME=/Users/funpin/Library/Java/JavaVirtualMachines/openjdk-21/Contents/Home MAVEN_USER_HOME=/private/tmp/mranked-maven-home MRANKED_MAVEN_REPOSITORY=/private/tmp/mranked-maven-repository .venv/bin/python -m operations.http_transition.rehearse --jar /private/tmp/mranked-review-v29-final-r2-build/m-ranked-backend-0.1.0-SNAPSHOT.jar --output /private/tmp/mranked-http-transition-final-v29-r2
rtk proxy .venv/bin/python -m operations.reverse_sync.rehearsal_contract /private/tmp/mranked-http-transition-final-v29-r2/reverse-http.json --output /private/tmp/mranked-http-transition-final-v29-r2/protocol-validation.json
```

All owned Compose containers/volumes and application processes were removed;
the supplied root JAR was unchanged. Large temporary fixtures/build products are
not copied into this evidence directory. Historical V28 failures and earlier
V29 runs remain retained separately. Cross-UID receipt permissions and actual
Nginx worker-drain semantics have their separate Linux proofs.

Production acceptance remains false: local protocol verification does not
satisfy external operator approval, deployed routing, live-provider evidence or
off-primary recovery ownership. Writer Gate W remains CLOSED.
