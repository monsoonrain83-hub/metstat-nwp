<?php
// Serve the existing catalog with a stable URL and a validator for each representation.
$file = @fopen(__DIR__ . '/data/manifest.json', 'rb');
if (!$file) { http_response_code(404); exit; }
$stat = fstat($file);
$gzip = function_exists('gzencode') && preg_match('/\bgzip\b(?!\s*;\s*q=0(?:\.0*)?\s*(?:,|$))/i', $_SERVER['HTTP_ACCEPT_ENCODING'] ?? '');
$tag = sprintf('W/"%x-%x-%x-%d"', $stat['ino'], $stat['mtime'], $stat['size'], (int)$gzip);
header('Content-Type: application/json; charset=utf-8');
header('Vary: Accept-Encoding');
header('Cache-Control: public, no-cache');
header('ETag: ' . $tag);
if (($_SERVER['HTTP_IF_NONE_MATCH'] ?? '') === $tag) { http_response_code(304); exit; }
if ($gzip) { header('Content-Encoding: gzip'); echo gzencode(stream_get_contents($file), 4); }
else { fpassthru($file); }
