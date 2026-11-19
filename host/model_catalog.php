<?php
// Stable catalog URL, explicit compression, and validators for unchanged content.
ini_set('zlib.output_compression', 'Off');
$file = @fopen(__DIR__ . '/data/manifest.json', 'rb');
if (!$file) { http_response_code(404); exit; }
$content = stream_get_contents($file);
fclose($file);
$gzip = false;
foreach (explode(',', $_SERVER['HTTP_ACCEPT_ENCODING'] ?? '') as $encoding) {
    $parts = array_map('trim', explode(';', strtolower($encoding)));
    if ($parts[0] !== 'gzip') continue;
    $quality = 1.0;
    foreach (array_slice($parts, 1) as $parameter) {
        if (preg_match('/^q\s*=\s*([0-9.]+)$/', $parameter, $match)) $quality = (float)$match[1];
    }
    $gzip = $quality > 0 && function_exists('gzencode');
}
$tag = 'W/"' . hash('sha256', $content) . '-' . (int)$gzip . '"';
header('Content-Type: application/json; charset=utf-8');
header('Vary: Accept-Encoding');
header('Cache-Control: public, no-cache');
header('ETag: ' . $tag);
if (in_array($tag, array_map('trim', explode(',', $_SERVER['HTTP_IF_NONE_MATCH'] ?? '')), true)) {
    http_response_code(304); exit;
}
if ($gzip) header('Content-Encoding: gzip');
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'HEAD') exit;
echo $gzip ? gzencode($content, 4) : $content;
