"""Compile actual reference snippets and execute assertions; optional installed JDKs only."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REFERENCES = ROOT / "java-coding-standards/references"


def blocks(name):
    return re.findall(r"```java\n(.*?)\n```", (REFERENCES / name).read_text(), re.S)


def installed_jdks():
    # Optional homes are supplied by the maintainer; never store machine paths in source.
    candidates = [(shutil.which("javac"), shutil.which("java"))]
    for home in os.environ.get("JAVA_TEST_HOMES", "").split(os.pathsep):
        if home:
            candidates.append((str(Path(home) / "bin/javac"), str(Path(home) / "bin/java")))
    found = {}
    for compiler, runtime in candidates:
        if not compiler or not runtime:
            continue
        try:
            result = subprocess.run([compiler, "-version"], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            continue
        match = re.search(r"javac (?:1\.)?(\d+)", result.stdout + result.stderr)
        if result.returncode == 0 and match:
            found[int(match.group(1))] = (compiler, runtime)
    return found


JDKS = installed_jdks()


class JavaExampleTests(unittest.TestCase):
    def compile_and_run(self, source, name, target, jdk):
        compiler, runtime = JDKS[jdk]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / (name + ".java")
            path.write_text(source)
            version_args = ["-source", str(target), "-target", str(target)] if jdk == 8 else ["--release", str(target)]
            result = subprocess.run([compiler, *version_args, "-Xlint:all", "-d", tmp, str(path)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([runtime, "-ea", "-cp", tmp, name], capture_output=True,
                                    text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(JDKS, "No installed functional JDK; examples not executed")
    def test_common_reference_snippets_across_installed_jdks(self):
        naming = blocks("naming-and-structure.md")[0]
        collections = blocks("collections.md")[0]
        resources = blocks("resources-and-security.md")[0]
        concurrency = blocks("concurrency.md")[0]
        jdbc = blocks("database.md")[0]
        source = """
import java.io.*;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import java.util.concurrent.locks.ReentrantLock;
public class ReferenceExamples {
    static final ReentrantLock lock = new ReentrantLock();
    %s
    static String load(Connection conn, long accountId) throws SQLException {
        %s
    }
    static void guarded(Runnable action) {
        %s
    }
    public static void main(String[] args) throws Exception {
        Integer firstId = Integer.valueOf(1000);
        Integer secondId = Integer.valueOf(1000);
        %s
        if (!same || !equalValue) throw new AssertionError("Value equality");
        List<String> names = new ArrayList<>(Arrays.asList("one", null, ""));
        %s
        if (!Arrays.equals(array, new String[] {"one"})) throw new AssertionError("Removal");
        List<? super Integer> sink = new ArrayList<Number>();
        sink.add(7);
        Object value = sink.get(0);
        if (!Integer.valueOf(7).equals(value)) throw new AssertionError("PECS");
        String[] backing = {"old"};
        List<String> fixed = Arrays.asList(backing);
        fixed.set(0, "new");
        if (!"new".equals(backing[0])) throw new AssertionError("Array view");
        try { fixed.add("bad"); throw new AssertionError("Expected failure"); }
        catch (UnsupportedOperationException expected) { }
        try { guarded(() -> { throw new IllegalStateException("expected"); }); }
        catch (IllegalStateException expected) { }
        if (lock.isLocked()) throw new AssertionError("Lock leaked");
        Path file = Files.createTempFile("java-skill-example", ".txt");
        try {
            Files.write(file, Arrays.asList("hello", "world"), StandardCharsets.UTF_8);
            if (!"hello".equals(readFirstLine(file))) throw new AssertionError("Read");
            Files.write(file, new byte[0]);
            if (readFirstLine(file) != null) throw new AssertionError("Empty file");
        } finally { Files.delete(file); }
    }
}
""" % (resources, jdbc, concurrency, naming, collections)
        for jdk in sorted(JDKS):
            if jdk >= 8:
                with self.subTest(runtime=jdk, target=jdk):
                    self.compile_and_run(source, "ReferenceExamples", jdk, jdk)

    def test_version_specific_reference_examples(self):
        examples = blocks("java-versions.md")
        for target, source in zip((11, 17, 21), examples):
            compatible = [jdk for jdk in JDKS if jdk >= target]
            with self.subTest(target=target):
                if not compatible:
                    self.skipTest("No JDK supports release %s; version example not executed" % target)
                for jdk in sorted(compatible):
                    with self.subTest(runtime=jdk):
                        self.compile_and_run(source, "Version%sExample" % target, target, jdk)


if __name__ == "__main__":
    unittest.main()
