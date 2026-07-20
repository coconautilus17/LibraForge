<?php
// Fixes 2 confirmed upstream m4b-tool 0.5.2 bugs (still present on master as of
// 2026-07-18, not fixed in any release) that make merge-time CUE chapter import
// silently produce zero chapters or crash the whole merge:
//   1. CueSheet::fromFile() never calls file_get_contents() on the file it finds
//      -- it parses the file's *pathname string* instead of its contents.
//   2. AbstractTagImprover::dumpTagDifference() throws a fatal TypeError when a
//      changed property (e.g. chapters) is an array, because it passes the raw
//      array into StringBuffer's string-only constructor.
// Usage: php -d phar.readonly=0 patch-m4b-tool-cuesheet.php <path-to-m4b-tool.phar>
$pharPath = $argv[1] ?? null;
if (!$pharPath || !file_exists($pharPath)) {
    fwrite(STDERR, "usage: php -d phar.readonly=0 patch-m4b-tool-cuesheet.php <path-to-m4b-tool.phar>\n");
    exit(1);
}
$phar = new Phar($pharPath);

$cueSheetFile = "src/library/Audio/CueSheet.php";
$content = $phar[$cueSheetFile]->getContent();
$old1 = "        \$fileToLoad = static::searchExistingMetaFile(\$reference, static::DEFAULT_FILENAME, \$fileName);\n        return new static(\$fileToLoad);\n";
if (strpos($content, $old1) === false) {
    fwrite(STDERR, "CueSheet.php: old string not found\n");
    exit(1);
}
$new1 = "        \$fileToLoad = static::searchExistingMetaFile(\$reference, static::DEFAULT_FILENAME, \$fileName);\n        return new static(\$fileToLoad ? file_get_contents(\$fileToLoad) : null);\n";
$content = str_replace($old1, $new1, $content);
echo "CueSheet.php patched OK\n";

$improverFile = "src/library/Audio/Tag/AbstractTagImprover.php";
$content2 = $phar[$improverFile]->getContent();
$old2 = "    protected function dumpTagDifference(\$tagDifference)\n    {\n        foreach (\$tagDifference as \$property => \$diff) {\n            \$before = (new StringBuffer((string)\$diff[\"before\"] === \"\" ? \"<empty>\" : \$diff[\"before\"]))->softTruncateBytesSuffix(static::DUMP_MAX_LEN, static::DUMP_TRUNCATE_SUFFIX);\n            \$after = (new StringBuffer(\$diff[\"after\"] ?? \"\"))->softTruncateBytesSuffix(static::DUMP_MAX_LEN, static::DUMP_TRUNCATE_SUFFIX);\n            \$this->info(sprintf(\"%15s: %s => %s\", \$property, \$before, \$after));\n        }\n    }\n";
if (strpos($content2, $old2) === false) {
    fwrite(STDERR, "AbstractTagImprover.php: old string not found\n");
    exit(1);
}
$new2 = "    protected function dumpTagDifference(\$tagDifference)\n    {\n        foreach (\$tagDifference as \$property => \$diff) {\n            \$beforeRaw = is_array(\$diff[\"before\"] ?? null) ? (count(\$diff[\"before\"]) . \" item(s)\") : (\$diff[\"before\"] ?? \"\");\n            \$afterRaw = is_array(\$diff[\"after\"] ?? null) ? (count(\$diff[\"after\"]) . \" item(s)\") : (\$diff[\"after\"] ?? \"\");\n            \$before = (new StringBuffer((string)\$beforeRaw === \"\" ? \"<empty>\" : \$beforeRaw))->softTruncateBytesSuffix(static::DUMP_MAX_LEN, static::DUMP_TRUNCATE_SUFFIX);\n            \$after = (new StringBuffer(\$afterRaw))->softTruncateBytesSuffix(static::DUMP_MAX_LEN, static::DUMP_TRUNCATE_SUFFIX);\n            \$this->info(sprintf(\"%15s: %s => %s\", \$property, \$before, \$after));\n        }\n    }\n";
$content2 = str_replace($old2, $new2, $content2);
echo "AbstractTagImprover.php patched OK\n";

$phar->startBuffering();
$phar[$cueSheetFile] = $content;
$phar[$improverFile] = $content2;
$phar->stopBuffering();
echo "Phar rewritten OK\n";
