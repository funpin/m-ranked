import assert from "node:assert/strict";
import test from "node:test";
import { overviewStatus } from "../lib/overview-status";

const max = { platform: "max" as const, accountCount: 1, enabledAccountCount: 1, connectedPlatformCount: 1,
  lastErrorCode: null, lastCheckedAt: "2026-08-01T12:00:00Z", statusCode: "polling" as const };
test("missing provider warnings cannot be hidden by a previous successful poll", () => {
  assert.deepEqual(overviewStatus(max,"max_phone_required"),{text:"Нужен MAX_USER_PHONE",kind:"warn"});
  assert.deepEqual(overviewStatus(max,"max_session_required"),{text:"Нужна авторизация MAX: auth-max",kind:"warn"});
  assert.deepEqual(overviewStatus({...max,platform:"vk"},"vk_token_required"),{text:"Нужен VK_ACCESS_TOKEN",kind:"warn"});
  assert.deepEqual(overviewStatus(max),{text:"активен",kind:"ok"});
});
test("legacy account-state precedence and exact error/empty text are retained", () => {
  assert.deepEqual(overviewStatus({...max,accountCount:0},"max_phone_required"),{text:"Аккаунт не добавлен",kind:"muted"});
  assert.deepEqual(overviewStatus({...max,enabledAccountCount:0},"max_phone_required"),{text:"Все аккаунты отключены",kind:"warn"});
  assert.deepEqual(overviewStatus({...max,lastErrorCode:"provider_error"}),{text:"Последний опрос завершился ошибкой",kind:"bad"});
  assert.deepEqual(overviewStatus({...max,lastCheckedAt:null}),{text:"Ожидает первого опроса",kind:"muted"});
  assert.deepEqual(overviewStatus({...max,platform:"all",connectedPlatformCount:3}),{text:"Подключено площадок: 3 из 4",kind:"ok"});
  assert.deepEqual(overviewStatus({...max,platform:"telegram",lastErrorCode:"telegram_error"}),{text:"telegram_error",kind:"bad"});
});
