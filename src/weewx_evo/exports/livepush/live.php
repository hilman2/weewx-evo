<?php
/*
 * live.php -- the station pushes its current readings here.
 *
 * The problem this solves: a skin published to a web host shows readings
 * that are as old as the last upload. Making them live otherwise means an
 * MQTT broker at the station, a port forwarded through the router, and a
 * certificate -- because a page served over https cannot open an
 * unencrypted websocket. That is three things to get right on somebody
 * else's network.
 *
 * This is one thing: weewx-evo POSTs its current readings here every few
 * seconds, and this writes them to a file beside itself. The page then reads
 * that file, which is static and served by the web server like any other.
 *
 * So PHP runs six times a minute -- when the station writes -- and not once
 * per visitor. A hundred people watching a storm cost nothing.
 *
 * ## Installing
 *
 * Nothing: it goes up with the rest of the skin. Set a token in the feed's
 * settings and the same token in `live.token` beside this file, or as the
 * environment variable WEEWX_EVO_LIVE_TOKEN.
 *
 * ## What it will not do
 *
 * Write anywhere but beside itself, under one fixed name. Accept a body
 * bigger than 64 kB. Accept anything but a POST with the right token. There
 * is nothing here that takes a path or a filename from the request, because
 * that is the mistake this kind of file exists to make.
 */

declare(strict_types=1);

const LIVE_FILE = 'live.json';
const MAX_BODY  = 65536;
/* Older than this and the page should say so rather than show it as now.
 * Written into the file so the reader does not have to be configured too. */
const STALE_AFTER = 300;

/* ---- the token ------------------------------------------------------- */

function expected_token(): string {
    $fromEnv = getenv('WEEWX_EVO_LIVE_TOKEN');
    if (is_string($fromEnv) && $fromEnv !== '') {
        return trim($fromEnv);
    }
    /* A file beside this one. Not in this file, so that the skin can be
     * updated without the token being overwritten -- and so it does not sit
     * in whatever repository the skin came from. */
    $path = __DIR__ . '/live.token';
    if (is_readable($path)) {
        return trim((string)file_get_contents($path));
    }
    return '';
}

function refuse(int $code, string $why): never {
    http_response_code($code);
    header('Content-Type: text/plain; charset=utf-8');
    echo $why;
    exit;
}

/* ---- reading -------------------------------------------------------- */

/* A GET hands back what is stored. Useful for checking the thing works at
 * all, and harmless: it is the same data the page reads from the file. */
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'GET') {
    $path = __DIR__ . '/' . LIVE_FILE;
    if (!is_readable($path)) {
        http_response_code(404);
        header('Content-Type: application/json; charset=utf-8');
        echo '{"error":"nothing has been pushed yet"}';
        exit;
    }
    header('Content-Type: application/json; charset=utf-8');
    /* Never cached. The whole point is that it is current, and a proxy
     * holding it for an hour would be worse than not having it. */
    header('Cache-Control: no-store, max-age=0');
    readfile($path);
    exit;
}

/* ---- writing -------------------------------------------------------- */

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    refuse(405, "POST to write, GET to read.\n");
}

$token = expected_token();
if ($token === '') {
    refuse(503, "No token is set on this server. Put one in live.token "
              . "beside live.php, or in WEEWX_EVO_LIVE_TOKEN.\n");
}

/* The header first, then a form field: a station behind a proxy that strips
 * unknown headers still gets through. */
$sent = $_SERVER['HTTP_X_WEEWX_TOKEN'] ?? ($_POST['token'] ?? '');
/* Compared in constant time. The difference is measurable over a network on
 * a token this short, and it costs one function call to not have to think
 * about it. */
if (!hash_equals($token, (string)$sent)) {
    /* 404, not 403. Saying "wrong token" confirms there is a right one. */
    refuse(404, "Not found.\n");
}

/* The request body.
 *
 * Read as a stream rather than with file_get_contents' offset and maxlen:
 * those two make it seek, and php://input is not seekable everywhere. The
 * limit still holds -- one byte past what is allowed is read, then refused
 * below.
 *
 * Under the CLI there is no php://input at all; the body is plain stdin.
 * That branch exists so this file can be tested without a web server, which
 * matters for a script that runs on somebody else's hosting and cannot be
 * debugged there. `PHP_SAPI` is set by PHP itself and cannot be forged by a
 * request. */
$where = PHP_SAPI === 'cli' ? 'php://stdin' : 'php://input';
$in = fopen($where, 'rb');
$body = $in === false ? '' : (string)stream_get_contents($in, MAX_BODY + 1);
if ($in !== false) {
    fclose($in);
}
if ($body === '') {
    refuse(400, "Empty body.\n");
}
if (strlen($body) > MAX_BODY) {
    refuse(413, "Too big.\n");
}

$data = json_decode($body, true);
if (!is_array($data)) {
    refuse(400, "That is not JSON.\n");
}

/* Stamped here as well as by the station. The station's clock is what the
 * reading is *from*; this is when it arrived, and the difference between the
 * two is the thing a page needs to decide whether to call itself live. */
$data['_received'] = time();
$data['_stale_after'] = STALE_AFTER;

$encoded = json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
if ($encoded === false) {
    refuse(400, "That JSON will not re-encode.\n");
}

/* Written beside and renamed. A visitor reading the file while it is being
 * written gets half a document, and half a JSON document is a parse error in
 * every browser -- which shows up as a page that goes blank once in a while
 * and cannot be reproduced. rename() is atomic on every filesystem a web
 * host runs on. */
$target = __DIR__ . '/' . LIVE_FILE;
$partial = $target . '.' . getmypid() . '.part';
if (file_put_contents($partial, $encoded, LOCK_EX) === false) {
    refuse(500, "Could not write beside live.php. Check the directory is "
              . "writable by the web server.\n");
}
if (!rename($partial, $target)) {
    @unlink($partial);
    refuse(500, "Could not replace " . LIVE_FILE . ".\n");
}

header('Content-Type: text/plain; charset=utf-8');
echo "ok " . strlen($encoded) . "\n";
