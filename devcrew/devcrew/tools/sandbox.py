import hashlib
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from devcrew.schemas import TestFailure, TestReport


def _error_type(msg):
    # "TypeError: unsupported ..." -> TypeError；"assert -1 == 3" -> AssertionError
    if msg.startswith("assert"):
        return "AssertionError"
    head = msg.split(":", 1)[0]
    return head if head.isidentifier() else "Error"


def run_pytest(code_files, test_files, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        for name, content in {**code_files, **test_files}.items():
            Path(d, name).write_text(content)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider",
                 "--junitxml=report.xml"],
                cwd=d, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return TestReport(all_passed=False, passed=0, failed=1, failures=[TestFailure(
                test_name="<timeout>", spec_ref="", error_type="Timeout",
                message=f"tests exceeded {timeout}s, possible infinite loop")], error_signature="timeout")
        xml_path = Path(d, "report.xml")
        if not xml_path.exists():
            return TestReport(all_passed=False, passed=0, failed=0, collection_error=True,
                              raw_output=proc.stdout + proc.stderr)
        root = ET.parse(xml_path).getroot()
        failures, passed, collection_error = [], 0, False
        for case in root.iter("testcase"):
            bad = case.find("failure")
            if bad is None:
                bad = case.find("error")
            if bad is None:
                if case.find("skipped") is None:
                    passed += 1
                continue
            name = case.get("name")
            m = re.match(r"test_(ac|ec)(\d+)", name)
            msg = bad.get("message", "")
            body = (bad.text or "").strip().splitlines()
            if msg == "collection failure":           # 测试文件导入失败
                collection_error = True
                msg = next((l[1:].strip() for l in reversed(body) if l.startswith("E ")), msg)
            # 只取 message 属性；bad.text 里含测试源码，不能给 Coder
            failures.append(TestFailure(
                test_name=name,
                spec_ref=f"{m.group(1).upper()}-{m.group(2)}" if m else "",
                error_type=_error_type(msg),
                message=msg[:500]))
        sig = hashlib.sha1("|".join(sorted(f"{f.test_name}:{f.error_type}" for f in failures)).encode()).hexdigest()[:12]
        return TestReport(all_passed=not failures and passed > 0, passed=passed, failed=len(failures),
                          collection_error=collection_error, failures=failures,
                          error_signature=sig if failures else "", raw_output=proc.stdout[-3000:])
