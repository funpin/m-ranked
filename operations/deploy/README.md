# Выкатка из GitHub Actions

Поток выпуска описан в [AGENTS.md](../../AGENTS.md) и
[CONTRIBUTING.md](../../CONTRIBUTING.md): выпускной PR `release: vГГГГ.М.N`
сливается в `main` → `release.yml` собирает архив, тег и GitHub Release →
`deploy.yml` ждёт одобрения в окружении `production` → по SSH вызывает
`deploy-release` на Сервере 2.

Здесь — то, что на сервере и в GitHub настраивается один раз руками.
Адреса, порты и ключи сюда не пишутся: репозиторий публичный.

## Как устроена выкатка на сервере

`deploy-release deploy <версия> <sha256> migrations=yes|no config=yes|no`:

1. Блокировка `/run/lock/m-ranked-release.lock` (общая с GC релизов).
2. Архив выпуска скачивается с GitHub Releases и сверяется с SHA-256,
   который прислал workflow (тот уже проверил провенанс сборки).
3. Дерево разворачивается в `/opt/m-ranked/releases/mranked-<версия>-s2`
   (`root:m-ranked-release-readers`, `0750`). Если lock-файлы те же, что у
   текущего релиза, `.venv` — ссылка на его среду; иначе ставится новая из
   lock-файлов с проверкой хешей. Код проверяется импортом.
4. Если выпуск меняет `operations/systemd`, `nginx`, `env`, `tmpfiles.d`
   или `redis`, выкатка останавливается: юниты на сервере живут с drop-in'ами
   и ставятся руками по [DEPLOY.md](../runbooks/DEPLOY.md). После этого —
   повтор с `config_reviewed`.
5. Новые миграции (которых нет в журнале `/var/lib/m-ranked/deploy/applied-migrations`)
   без `apply_migrations` останавливают выкатку. С ним — проверка, что
   последний дамп моложе 26 часов, и применение по одной от
   `migration_owner`. Миграция с строкой `-- deploy: manual` (например,
   требующая остановки сборщиков, как 0033) автоматически не применяется
   никогда: оператор применяет её по DEPLOY.md и дописывает имя в журнал.
6. Атомарная замена `current`, `build.conf` nginx (`BUILD_ID-короткий sha`),
   reload nginx, перезапуск API, сайта, прогрева, анализа, приёма и бота.
7. Проверка: `health/live`, `health/ready` и HTML сайта с `?dpl=<commit>`
   этого выпуска. Не прошла — прежний `current` и `build.conf` возвращаются,
   службы перезапускаются, выкатка падает.
8. Запись `/opt/m-ranked/deployments/<версия>/activation.json`.

Откат — та же выкатка прежнего выпуска (`Deploy` → Run workflow → версия):
его дерево ещё на сервере, повторно проверяется отпечаток. Миграции назад не
откатываются — они пишутся расширением схемы, которое прежний код переносит.
Старые релизы удаляет host-storage-gc (DEPLOY.md, раздел 8), не выкатка.

## Один раз на Сервере 2 (root)

```bash
# 1. Пользователь без оболочки и паролей — только для принудительной команды.
useradd --system --create-home --home-dir /var/lib/m-ranked-deploy \
  --shell /bin/bash m-ranked-deploy
passwd -l m-ranked-deploy

# 2. Скрипты — вне релиза: выкатка не может подменить сама себя.
install -d -o root -g root -m 0755 /usr/local/libexec/m-ranked
install -o root -g root -m 0755 operations/deploy/deploy-release.sh \
  /usr/local/libexec/m-ranked/deploy-release
install -o root -g root -m 0755 operations/deploy/deploy-entrypoint.sh \
  /usr/local/libexec/m-ranked/deploy-entrypoint
install -o root -g root -m 0640 operations/deploy/deploy.env.example /etc/m-ranked/deploy.env

# 3. sudo — ровно один скрипт; аргументы он проверяет сам.
install -o root -g root -m 0440 operations/deploy/sudoers.example \
  /etc/sudoers.d/m-ranked-deploy
visudo -cf /etc/sudoers.d/m-ranked-deploy

# 4. Журнал применённых миграций. Сначала — все, что уже в базе.
#    Сверьте последнюю применённую по DEPLOY.md, затем:
install -d -o root -g root -m 0750 /var/lib/m-ranked/deploy
ls /opt/m-ranked/current/db/migrations | grep -E '^[0-9]{4}_.*\.sql$' \
  > /var/lib/m-ranked/deploy/applied-migrations
#    Если миграции применялись вне релиза (например, 0089 31.10.2026),
#    допишите их имена: echo 0089_....sql >> .../applied-migrations

# 5. Ключ GitHub Actions: только принудительная команда, без пробросов.
install -d -o m-ranked-deploy -g m-ranked-deploy -m 0700 /var/lib/m-ranked-deploy/.ssh
echo 'restrict,command="/usr/local/libexec/m-ranked/deploy-entrypoint" ssh-ed25519 AAAA... github-actions-deploy' \
  > /var/lib/m-ranked-deploy/.ssh/authorized_keys
chown m-ranked-deploy: /var/lib/m-ranked-deploy/.ssh/authorized_keys
chmod 0600 /var/lib/m-ranked-deploy/.ssh/authorized_keys
```

Если в `sshd_config` есть `AllowUsers`/`AllowGroups`, добавьте туда
`m-ranked-deploy`. Вход только по ключу и fail2ban не меняются.
Проверка с машины оператора: `ssh -i <ключ> m-ranked-deploy@<сервер> status`.

Скрипты в `/usr/local/libexec/m-ranked/` обновляются только так же, руками,
после просмотра изменений в `operations/deploy/`.

## Один раз в GitHub (владелец репозитория)

Ключ выкатки генерируется отдельно от личных и нигде, кроме секрета, не
хранится:

```bash
ssh-keygen -t ed25519 -N '' -C github-actions-deploy -f deploy_key
ssh-keyscan -p <порт> <сервер> > known_hosts   # сверить отпечаток с сервером
```

Settings → Environments → `production`:

- Required reviewers — кто одобряет выкатку; Prevent self-review.
- Deployment branches and tags — Selected: `main`.
- Secrets: `DEPLOY_HOST`, `DEPLOY_PORT`, `DEPLOY_USER` (= `m-ranked-deploy`),
  `DEPLOY_SSH_KEY` (содержимое `deploy_key`), `DEPLOY_KNOWN_HOSTS`
  (содержимое `known_hosts`). После загрузки удалите `deploy_key` с диска.

Правила веток и остальное — `operations/github/setup-repository.sh`.
