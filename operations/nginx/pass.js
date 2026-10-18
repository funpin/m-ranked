// Проверка на настоящий браузер (njs). Ставится в /etc/m-ranked/nginx/pass.js и
// подключается из traffic.conf.
//
// Почему. 18.10.2026 сайт выкачивали с тысяч домашних адресов по одному запросу
// с адреса и с браузерными User-Agent: класс human, лимиты по адресу не
// срабатывают, а каждая холодная страница стоит ~0,9 с процессора. Такие
// обходчики скачивают только HTML и скриптов не выполняют. Поэтому анонимный
// промах страницы без отметки «проверен» получает от шлюза крошечную страницу:
// скрипт решает лёгкую задачу (SHA-256 с BITS нулевыми битами, доли секунды),
// /__pass проверяет решение и ставит подписанную куку. Попадания в кэш, переходы
// по уже открытому сайту с кукой, API и роботы с честным User-Agent этого не
// видят.
//
// Кука не привязана к адресу: у мобильных он меняется. Подпись — HMAC-SHA256 с
// секретом из /etc/m-ranked/nginx/pass-secret.conf ($m_ranked_pass_secret).
// Без секрета проверка выключается (всех пускает) и пишет ошибку в журнал:
// сломанная настройка не должна закрыть сайт людям.

import cr from 'crypto';

const COOKIE = 'mr_pass';
const PASS_SECONDS = 7 * 86400;
const CHALLENGE_SECONDS = 120;
const BITS = 10;
const MAX_TARGET = 2048;

function now() {
    return Math.floor(Date.now() / 1000);
}

function secret(r) {
    const value = r.variables.m_ranked_pass_secret || '';
    return value.length >= 32 ? value : null;
}

function sign(key, data) {
    return cr.createHmac('sha256', key).update(data).digest('base64url');
}

function same(a, b) {
    if (a.length !== b.length) {
        return false;
    }
    let diff = 0;
    for (let i = 0; i < a.length; i++) {
        diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
    }
    return diff === 0;
}

// Подписанная пара «срок.подпись» с префиксом назначения: кука и задача
// подписываются разными префиксами, чтобы одну нельзя было выдать за другую.
function signedUntil(key, kind, value) {
    const parts = (value || '').split('.');
    if (parts.length < 2 || !/^[0-9]{10}$/.test(parts[0])) {
        return null;
    }
    const sig = parts.pop();
    if (!same(sig, sign(key, kind + '|' + parts.join('.')))) {
        return null;
    }
    return Number(parts[0]);
}

// js_set: «1», если у запроса действующая кука (или проверка выключена).
function valid(r) {
    const key = secret(r);
    if (key === null) {
        r.error('m-ranked pass: no secret, browser check disabled');
        return '1';
    }
    const until = signedUntil(key, 'pass', r.variables.cookie_mr_pass);
    return until !== null && until >= now() ? '1' : '0';
}

function leadingZeroBits(bytes, bits) {
    for (let i = 0; i < bits; i++) {
        if (bytes[i >> 3] & (0x80 >> (i & 7))) {
            return false;
        }
    }
    return true;
}

function safeTarget(value) {
    // Только путь своего сайта: «/x», но не «//host» и не «/\host».
    if (!value || value.length > MAX_TARGET || value[0] !== '/' || value[1] === '/' || value[1] === '\\'
        || /[\r\n]/.test(value)) {
        return '/';
    }
    return value;
}

function noStore(r) {
    r.headersOut['Cache-Control'] = 'no-store';
    // Публичный слой кэширует по X-Accel-Expires: «0» — не класть в кэш.
    r.headersOut['X-Accel-Expires'] = '0';
}

function page(nonce, challenge) {
    return `<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>m-ranked</title>
<style nonce="${nonce}">
:root{color-scheme:light dark;--bg:#fff;--fg:#0d1117;--muted:#57606a}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e}}
html,body{height:100%;margin:0}body{display:grid;place-items:center;background:var(--bg);color:var(--fg);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}main{max-width:28rem;padding:0 16px;text-align:center}
p{margin:.25rem 0}.muted{color:var(--muted);font-size:14px}
</style></head><body><main>
<p id="state">Открываем страницу…</p>
<noscript><p>Для этой страницы нужен JavaScript: включите его и обновите страницу.</p></noscript>
<p class="muted">m-ranked проверяет, что страницу открыл браузер, а не программа для сбора данных.</p>
</main>
<script nonce="${nonce}">
(function(){
var c=${JSON.stringify(challenge)},bits=${BITS};
function sha(m){var k=[1116352408,1899447441,3049323471,3921009573,961987163,1508970993,2453635748,2870763221,3624381080,310598401,607225278,1426881987,1925078388,2162078206,2614888103,3248222580,3835390401,4022224774,264347078,604807628,770255983,1249150122,1555081692,1996064986,2554220882,2821834349,2952996808,3210313671,3336571891,3584528711,113926993,338241895,666307205,773529912,1294757372,1396182291,1695183700,1986661051,2177026350,2456956037,2730485921,2820302411,3259730800,3345764771,3516065817,3600352804,4094571909,275423344,430227734,506948616,659060556,883997877,958139571,1322822218,1537002063,1747873779,1955562222,2024104815,2227730452,2361852424,2428436474,2756734187,3204031479,3329325298],
h=[1779033703,3144134277,1013904242,2773480762,1359893119,2600822924,528734635,1541459225],b=[],i,j;
m=unescape(encodeURIComponent(m));for(i=0;i<m.length;i++)b[i>>2]|=m.charCodeAt(i)<<(24-(i%4)*8);
b[m.length>>2]|=0x80<<(24-(m.length%4)*8);b[((m.length+8>>6)+1)*16-1]=m.length*8;
for(i=0;i<b.length;i+=16){var w=[],a=h.slice(0);for(j=0;j<64;j++){if(j<16)w[j]=b[i+j]|0;else{var x=w[j-15],y=w[j-2];
w[j]=(((x>>>7|x<<25)^(x>>>18|x<<14)^x>>>3)+w[j-7]+((y>>>17|y<<15)^(y>>>19|y<<13)^y>>>10)+w[j-16])|0;}
var t1=(a[7]+((a[4]>>>6|a[4]<<26)^(a[4]>>>11|a[4]<<21)^(a[4]>>>25|a[4]<<7))+(a[4]&a[5]^~a[4]&a[6])+k[j]+w[j])|0,
t2=(((a[0]>>>2|a[0]<<30)^(a[0]>>>13|a[0]<<19)^(a[0]>>>22|a[0]<<10))+(a[0]&a[1]^a[0]&a[2]^a[1]&a[2]))|0;
a=[(t1+t2)|0].concat(a);a[4]=(a[4]+t1)|0;a.pop();}for(j=0;j<8;j++)h[j]=(h[j]+a[j])|0;}return h;}
for(var n=0;n<1e7;n++){if((sha(c+":"+n)[0]>>>(32-bits))===0)break;}
location.replace("/__pass?c="+encodeURIComponent(c)+"&n="+n+"&to="+encodeURIComponent(location.pathname+location.search));
})();
</script></body></html>
`;
}

// Шлюз: анонимный промах страницы без куки. Код 429 — не 5xx (тревога «ответы
// людям 5xx» не срабатывает), а публичный слой вместо него отдаст устаревшую
// копию страницы, если она есть.
function challenge(r) {
    const key = secret(r);
    if (key === null) {
        r.return(503, 'Сервер занят, повторите позже.\n');
        return;
    }
    const nonce = Buffer.from(crypto.getRandomValues(new Uint8Array(12))).toString('base64url');
    const body = [String(now() + CHALLENGE_SECONDS), Buffer.from(crypto.getRandomValues(new Uint8Array(12))).toString('hex')]
        .join('.');
    const token = body + '.' + sign(key, 'chal|' + body);
    noStore(r);
    r.headersOut['Content-Type'] = 'text/html; charset=utf-8';
    r.headersOut['Content-Security-Policy'] = `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'; `
        + "base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
    r.return(429, page(nonce, token));
}

// /__pass?c=<задача>&n=<решение>&to=<путь>: проверить решение, поставить куку
// и вернуть на страницу.
function issue(r) {
    const key = secret(r);
    noStore(r);
    // Сырые значения: задача и решение кодирования не требуют (base64url, цифры).
    const c = r.variables.arg_c || '';
    const n = r.variables.arg_n || '';
    const until = key === null ? null : signedUntil(key, 'chal', c);
    const solved = until !== null && until >= now() && /^[0-9]{1,8}$/.test(n)
        && leadingZeroBits(cr.createHash('sha256').update(c + ':' + n).digest(), BITS);
    if (!solved) {
        r.headersOut['Content-Type'] = 'text/plain; charset=utf-8';
        r.return(403, 'Проверка не пройдена: обновите страницу.\n');
        return;
    }
    const expires = String(now() + PASS_SECONDS);
    r.headersOut['Set-Cookie'] = `${COOKIE}=${expires}.${sign(key, 'pass|' + expires)}; Max-Age=${PASS_SECONDS}; `
        + 'Path=/; Secure; HttpOnly; SameSite=Lax';
    let target = '/';
    try {
        target = safeTarget(decodeURIComponent(r.variables.arg_to || '/'));
    } catch (e) {
        target = '/';
    }
    r.return(303, target);
}

export default { valid, challenge, issue };
