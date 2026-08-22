# -*- coding: utf-8 -*-
"""이 저장소는 공개다 — 추적 파일에 방 사람들의 것이 들어가면 안 된다.

왜 검사로 두는가 (2026-08-02)
  공개 전환 점검에서 실제 연락처 두 건(이메일·휴대전화)과 참여자 실명 13명분이
  검사 자료·주석에 굳어 있었다. 발행본에서는 그렇게 공들여 가리면서, 정작
  저장소에는 원본이 들어 있었다. 한 번 고치고 끝낼 일이 아니다 — 검사 자료는
  실제 대화에서 가져올 때 가장 그럴듯해서, 다음에도 같은 손이 간다.

명단은 저장소에 없다
  실명·연락처의 원본은 `output/participants.json` 과 `config/members.json` 인데
  둘 다 .gitignore 다. 그래서 이 검사는 **관리자 컴퓨터에서만** 실제 대조를 하고,
  그 파일이 없는 포크·CI 에서는 조용히 건너뛴다. 명단을 검사에 적어 두면 검사
  자체가 명단이 되므로, 건너뛰는 편이 맞다.

가명을 쓴다
  기여자가 새 검사 자료를 만들 때는 지어낸 이름을 쓴다. 실제 참여자와 겹치지
  않게, 이 검사가 알려 준다.
"""
from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 본인 이름은 뺀다. 저장소 주인이고, 예시·문서에서 화자로 쓰인다.
OWNER_NAMES = {"김종원"}

# 공개된 기관 연락처는 개인정보가 아니다 — 감추면 오히려 안내가 사라진다.
PUBLIC_CONTACTS = {"help@sasw.or.kr", "0231495000", "0263606529"}

# 검사·문서에 일부러 두는 예시 주소
PLACEHOLDER_DOMAINS = ("example.com", "example.org", "example.net", "example.or.kr",
                       "example.co.kr", "test.com", "x.com", "y.com",
                       "b.co.kr", "b.or.kr")

# 도메인이 진짜여도(gmail.com·sasw.or.kr) 앞자리가 이러면 서식의 빈칸이다.
# 도메인째 넘기지 않는 이유: 그러면 진짜 gmail 주소가 그대로 통과한다.
PLACEHOLDER_LOCALS = ("you", "someone", "member", "member1", "member2",
                      "name", "user", "admin", "a", "b", "c", "d", "e")

# 탐지기 검사에 쓰는 **지어낸** 연락처.
#
# 이것들은 예시 도메인·더미 번호를 쓸 수 없다. pii.py 가 example.com 과
# 1234-5678 류를 일부러 넘기기 때문에, 그런 값으로는 "가려야 할 것을 가리는지"를
# 검사할 수 없다. 그래서 진짜처럼 생긴 값이 필요하고, 진짜처럼 생겼으니 여기에
# 적어 둔다. 늘리기 전에 아래 test_synthetic_values_are_not_real_after_all 를 볼 것.
SYNTHETIC = {"nobody9f3a@hanmail.net", "01000004321"}

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
_PHONE = re.compile(r"(?<!\d)01[016789][-. ]?\d{3,4}[-. ]?\d{4}(?!\d)")


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8").stdout.split()
    skip = {"package-lock.json"}
    return [ROOT / f for f in out if f not in skip]


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


class NoRealNamesTest(unittest.TestCase):
    def participants(self) -> set[str]:
        p = ROOT / "output" / "participants.json"
        if not p.exists():
            self.skipTest("output/participants.json 이 없다 (관리자 컴퓨터가 아님)")
        raw = json.loads(p.read_text(encoding="utf-8"))
        return {x["nickname"] for x in raw["participants"]
                if len(x.get("nickname") or "") >= 2} - OWNER_NAMES

    def test_no_participant_name_is_committed(self):
        names = self.participants()
        found: dict[str, list[str]] = {}
        for path in tracked_files():
            text = read(path)
            for n in names:
                if n in text:
                    found.setdefault(n, []).append(rel(path))
        self.assertEqual(
            found, {},
            "추적 파일에 참여자 실명이 있다 — 지어낸 이름으로 바꿔라: %s" % found)


class NoRealContactsTest(unittest.TestCase):
    """연락처는 명단이 없어도 검사한다 — 모양만으로 충분히 걸러진다."""

    def test_no_personal_mobile_number(self):
        # 예시 번호(1234-5678 류)와 같은 숫자 반복은 넘긴다. 판정은 탐지기와 같은
        # 규칙을 쓴다 — 두 곳이 다르면 한쪽이 통과시킨 것을 다른 쪽이 못 잡는다.
        from scripts import pii
        bad = []
        for path in tracked_files():
            for m in _PHONE.finditer(read(path)):
                raw = m.group(0)
                if pii._is_dummy_phone(raw):
                    continue
                digits = re.sub(r"\D", "", raw)
                if digits in PUBLIC_CONTACTS or digits in SYNTHETIC:
                    continue
                bad.append("%s: %s" % (rel(path), raw))
        self.assertEqual(bad, [], "추적 파일에 개인 휴대전화가 있다: %s" % bad)

    def test_no_personal_email_outside_placeholder_domains(self):
        bad = []
        for path in tracked_files():
            for m in _EMAIL.finditer(read(path)):
                v = m.group(0).lower()
                if v in PUBLIC_CONTACTS or v in SYNTHETIC:
                    continue
                if v.endswith(PLACEHOLDER_DOMAINS):
                    continue
                if v.split("@")[0] in PLACEHOLDER_LOCALS:
                    continue
                if v.startswith("@") or "@types" in v:      # npm 스코프
                    continue
                bad.append("%s: %s" % (rel(path), v))
        self.assertEqual(
            bad, [],
            "추적 파일에 개인 이메일로 보이는 것이 있다: %s" % bad)

    def test_synthetic_values_are_not_real_after_all(self):
        """지어낸 값이 실제로는 방에 있는 값이면 지어낸 것이 아니다.

        검사 자료를 만들 때 실제 대화에서 값을 집어오는 것이 가장 자연스러워서,
        이번에도 그렇게 굳어 있었다(실측 2026-08-02). 원장이 있는 컴퓨터에서는
        대조로 막는다.
        """
        ledger = ROOT / "output" / "messages.jsonl"
        if not ledger.exists():
            self.skipTest("output/messages.jsonl 이 없다 (관리자 컴퓨터가 아님)")
        blob = ledger.read_text(encoding="utf-8")
        digits_only = re.sub(r"\D", "", blob)
        for v in SYNTHETIC:
            with self.subTest(value=v):
                if v.isdigit():
                    self.assertNotIn(v, digits_only,
                                     "%s 은 실제 대화에 있는 번호다" % v)
                else:
                    self.assertNotIn(v, blob, "%s 은 실제 대화에 있는 주소다" % v)


class ArchiveContentIsNotCommittedTest(unittest.TestCase):
    """대화 원문·보고서는 저장소에 넣지 않는다.

    실측 2026-08-02: 한 번 쓰고 버릴 이관 스크립트(dedupe_backfill_20260728.py)에
    실제 스레드 제목·요지 12건이 통째로 박혀 있었다. 발행본에서는 원문을 빼면서
    코드에는 남긴 꼴이었다.
    """

    def test_data_paths_stay_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for path in ("/output/", "/config/members.json", "/config/pii_allow.json"):
            with self.subTest(path=path):
                self.assertIn(path, ignore)

    def test_data_folders_are_ignored_wholesale_not_enumerated(self):
        """`assets/`·`inbox/` 는 통째로 무시하고 예외만 적는다.

        하위 폴더를 하나씩 열거하는 방식은 이미 두 번 샜다 — `/KakaoTalk_*.txt` 가
        파일 하나만 잡아 내보내기 **폴더**가 빠져나갔고(2026-07-27, 483MB), 폴더
        이름이 'Chats'/'Chat' 으로 갈려 좁게 잡은 규칙이 또 빠져나갔다. 열거식은
        새 폴더가 생길 때마다 다시 새고, 새는 곳이 공개 저장소라 되돌릴 수 없다.
        """
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for blanket in ("/assets/*", "/inbox/*"):
            with self.subTest(blanket=blanket):
                self.assertIn(blanket, ignore,
                              "%s 로 통째로 막아야 합니다 — 하위 폴더 열거는 샙니다"
                              % blanket)

    def test_no_conversation_export_is_tracked(self):
        bad = [rel(p) for p in tracked_files()
               if p.name.startswith("KakaoTalk_") and p.suffix == ".txt"]
        self.assertEqual(bad, [], "카톡 내보내기 원문이 추적되고 있다: %s" % bad)

    def test_no_data_directory_is_tracked(self):
        """`assets/`·`logs/`·`inbox/` 아래에 추적되는 파일이 없다.

        `output/` 은 위에서 .gitignore 에 있는지로 본다. 이 셋은 다르다 —
        일부만 무시하고 일부는(README 처럼) 일부러 추적한다. 그래서 "무시 규칙이
        있는가"가 아니라 "실제로 무엇이 추적되고 있는가"를 본다.
        """
        allowed = {"inbox/README.md"}
        bad = [rel(p) for p in tracked_files()
               if rel(p).split("/")[0] in ("assets", "logs")
               or (rel(p).startswith("inbox/") and rel(p) not in allowed)]
        self.assertEqual(bad, [], "대화 데이터 폴더의 파일이 추적되고 있다: %s" % bad)

    def test_nothing_is_left_untracked_and_unignored(self):
        """추적도 무시도 되지 않은 데이터 파일이 없다.

        .gitignore 가 `assets/` 아래를 하위 폴더마다 하나씩 열거해 무시한다 —
        staging·design-source·files·images·Kakao*·thumbs·videos. 열거식이라
        나중에 `assets/audio/` 가 생기면 **추적도 무시도 안 된 상태**가 되고,
        `git add -A` 한 번에 공개 저장소로 들어간다. `inbox/` 는 이미 안전한
        방식을 쓴다(`/inbox/*` + README 만 예외).

        `git status --porcelain` 이 데이터 경로를 하나라도 물고 오면 실패한다.
        지금 당장 새는 것이 없어도, 새기 **전에** 알려주는 것이 이 검사의 일이다.
        """
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout
        watched = ("assets/", "logs/", "inbox/", "output/", "firestore-payload/",
                   "site/", "hosting/")
        leaks = []
        for line in out.splitlines():
            # 앞 두 칸이 상태, 그 뒤가 경로. 이름에 공백이 있으면 따옴표로 온다.
            path = line[3:].strip().strip('"')
            if line[:2].strip() == "??" and path.startswith(watched):
                leaks.append(path)
        self.assertEqual(leaks, [],
                         "추적도 무시도 되지 않은 데이터 경로가 있다 — "
                         ".gitignore 에 넣으세요: %s" % leaks)

    def test_no_service_account_key_is_tracked(self):
        # 표식을 이어 붙여 만든다. 통째로 적으면 이 파일 자신이 걸린다.
        marker = '"type": "service' + '_account"'
        bad = [rel(p) for p in tracked_files()
               if "serviceaccount" in p.name.lower() or marker in read(p)]
        self.assertEqual(bad, [], "서비스 계정 키가 추적되고 있다: %s" % bad)


if __name__ == "__main__":
    unittest.main()
