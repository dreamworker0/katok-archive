# -*- coding: utf-8 -*-
"""설치형(PWA) 계약.

지키려는 것이 두 가지다.
  1) 설치가 실제로 되는가 — 매니페스트 필수 항목, 아이콘 파일과 선언한 크기의 일치.
  2) 캐시가 대화·사진을 저장하지 않는가 — 이 프로젝트의 전제(배포본이 공개돼도
     개인정보가 새지 않는다)를 서비스 워커도 지켜야 한다.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import struct
import unittest


ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
MANIFEST = WEB / "manifest.webmanifest"


def precache_list(source: str, name: str) -> list[str]:
    """sw.js 의 미리 캐시 목록(`var NAME = [...]`)에 적힌 경로를 읽는다."""
    block = re.search(r"var %s = \[(.*?)\];" % name, source, re.S)
    if block is None:
        raise AssertionError("%s 목록을 찾지 못했습니다" % name)
    return re.findall(r'"([^"]+)"', block.group(1))


def png_size(path: Path) -> tuple[int, int]:
    """PNG 머리말에서 가로x세로를 읽는다. (Pillow 없이 확인하려고 직접 읽는다)"""
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("PNG 파일이 아닙니다: %s" % path)
    width, height = struct.unpack(">II", raw[16:24])
    return width, height


class ManifestContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_manifest_declares_what_installation_requires(self):
        m = self.manifest
        self.assertEqual("standalone", m["display"])
        self.assertEqual("/", m["start_url"])
        self.assertEqual("/", m["scope"])
        self.assertEqual("ko", m["lang"])
        self.assertTrue(m["name"])
        # short_name 은 홈 화면 아이콘 아래에 들어간다. 길면 잘린다.
        self.assertTrue(m["short_name"])
        self.assertLessEqual(len(m["short_name"]), 12)
        self.assertTrue(m["description"])

    def test_manifest_colors_match_the_stylesheet_background(self):
        # 스플래시·주소창 색이 화면과 다르면 열 때마다 색이 튄다.
        css = (WEB / "styles.css").read_text(encoding="utf-8")
        light_bg = re.search(r"--bg:\s*(#[0-9A-Fa-f]{6})", css).group(1)
        self.assertEqual(light_bg.lower(), self.manifest["theme_color"].lower())
        self.assertEqual(light_bg.lower(), self.manifest["background_color"].lower())

    def test_icons_exist_at_the_sizes_they_claim(self):
        icons = self.manifest["icons"]
        self.assertTrue(icons)
        for icon in icons:
            with self.subTest(src=icon["src"]):
                path = WEB / icon["src"]
                self.assertTrue(path.is_file(), "아이콘 파일이 없습니다: %s" % path)
                self.assertEqual("image/png", icon["type"])
                declared = icon["sizes"]
                width, height = png_size(path)
                self.assertEqual("%dx%d" % (width, height), declared)

    def test_icons_cover_install_and_adaptive_masking(self):
        by_purpose: dict[str, set[int]] = {}
        for icon in self.manifest["icons"]:
            side = int(icon["sizes"].split("x")[0])
            by_purpose.setdefault(icon.get("purpose", "any"), set()).add(side)
        # 크롬은 설치 자격에 192·512 를 본다.
        self.assertLessEqual({192, 512}, by_purpose.get("any", set()))
        # maskable 이 없으면 안드로이드 런처가 흰 여백째로 잘라 넣는다.
        self.assertTrue(by_purpose.get("maskable"))

    def test_apple_touch_icon_is_shipped_for_ios_home_screen(self):
        # iOS 는 매니페스트 아이콘을 쓰지 않는다. 별도 파일이 있어야 한다.
        path = WEB / "icons" / "apple-touch-icon.png"
        self.assertTrue(path.is_file())
        self.assertEqual((180, 180), png_size(path))


class FaviconMatchesTheAppTests(unittest.TestCase):
    """탭 파비콘이 화면 팔레트 안에 있고, 홈 화면 아이콘과 같은 그림인지."""

    @classmethod
    def setUpClass(cls):
        cls.svg = (WEB / "favicon.svg").read_text(encoding="utf-8")

    def test_favicon_is_generated_not_hand_edited(self):
        # 손으로 고치면 홈 화면 아이콘과 색이 어긋난다. 예전에 파비콘만 파란색으로
        # 남아 크림색 배경과 겉돌았다.
        self.assertIn("build_pwa_icons.py", self.svg)
        self.assertIn("직접 고치지 말 것", self.svg)

    def test_favicon_dropped_the_old_blue(self):
        self.assertNotIn("3b6fe0", self.svg.lower())

    def test_favicon_uses_the_same_colours_as_the_home_screen_icons(self):
        from scripts import build_pwa_icons

        self.assertIn(build_pwa_icons.ICON_BG.lower(), self.svg.lower())
        self.assertIn(build_pwa_icons.ICON_MARK.lower(), self.svg.lower())

    def test_icon_paper_is_the_stylesheet_surface_colour(self):
        from scripts import build_pwa_icons

        css = (WEB / "styles.css").read_text(encoding="utf-8").lower()
        self.assertIn(build_pwa_icons.ICON_MARK.lower(), css)

    def test_icon_background_is_a_warm_brown(self):
        """바탕색은 따뜻한 갈색이어야 한다 — 파란색으로 되돌아가지 않게.

        팔레트 토큰과 똑같을 필요는 없다(강조색보다 진한 갈색을 일부러 골랐다).
        대신 색조로 확인한다: 갈색은 빨강 > 초록 > 파랑 이다.
        """
        from scripts import build_pwa_icons

        raw = build_pwa_icons.ICON_BG.lstrip("#")
        r, g, b = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
        self.assertGreater(r, g, "빨강이 초록보다 커야 따뜻한 색이다")
        self.assertGreater(g, b, "초록이 파랑보다 커야 갈색 계열이다")
        # 탭에서 크림색 배경과 구분되게 충분히 어두워야 한다.
        self.assertLess((r + g + b) / 3, 190)


class ServiceWorkerPrivacyContractTests(unittest.TestCase):
    """서비스 워커가 대화·사진·인증을 저장하지 않는지 본다."""

    @classmethod
    def setUpClass(cls):
        cls.sw = (WEB / "sw.js").read_text(encoding="utf-8")

    def test_private_hosts_are_never_cached(self):
        for host in (
            "firestore.googleapis.com",
            "firebasestorage.googleapis.com",
            "identitytoolkit.googleapis.com",
            "securetoken.googleapis.com",
            "cloudfunctions.net",
        ):
            with self.subTest(host=host):
                self.assertIn(host, self.sw)
        self.assertIn("PRIVATE_HOSTS", self.sw)
        self.assertIn("if (isPrivate(url)) return;", self.sw)

    def test_same_origin_auth_handler_is_excluded_too(self):
        # Firebase 인증 핸들러는 /__/auth/... 로 같은 출처에 있다. 호스트 목록만으로는
        # 걸러지지 않아 경로를 따로 본다.
        self.assertIn('url.pathname.indexOf("/__/auth") === 0', self.sw)

    def test_only_get_requests_are_intercepted(self):
        self.assertIn('if (request.method !== "GET") return;', self.sw)

    def test_precache_never_includes_conversation_data(self):
        # 주석이 아니라 실제 목록을 본다 — 머리말에는 "data.js 는 캐시하지 않는다"고
        # 적혀 있으므로 파일 전체를 훑으면 그 설명에 걸린다.
        cached = []
        for name in ("SHELL_CORE", "SHELL_OPTIONAL", "ASSET_CORE"):
            cached += precache_list(self.sw, name)
        self.assertTrue(cached)
        for entry in cached:
            with self.subTest(entry=entry):
                self.assertNotIn("data.js", entry)
                self.assertNotIn("assets/", entry)

    def test_sign_out_can_empty_the_caches(self):
        self.assertIn("CLEAR_CACHES", self.sw)
        self.assertIn("CLEAR_CACHES", (WEB / "pwa.js").read_text(encoding="utf-8"))


class ServiceWorkerBehaviourContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sw = (WEB / "sw.js").read_text(encoding="utf-8")

    def _precache_list(self, name: str) -> list[str]:
        return precache_list(self.sw, name)

    def test_precached_local_files_all_exist(self):
        for name in ("SHELL_CORE", "ASSET_CORE"):
            for entry in self._precache_list(name):
                if entry == "/":
                    continue  # 껍데기 진입점. index.hosting.html 로 서빙된다.
                with self.subTest(entry=entry):
                    self.assertTrue(
                        (WEB / entry).is_file(),
                        "미리 캐시하는 파일이 web/ 에 없습니다: %s" % entry,
                    )

    def test_shell_precache_matches_the_scripts_the_page_loads(self):
        shell = set(self._precache_list("SHELL_CORE"))
        source = (WEB / "index.hosting.html").read_text(encoding="utf-8")
        # 페이지가 부르는 로컬 스크립트는 전부 오프라인에서도 있어야 한다.
        for src in re.findall(r'<script src="([^"/][^"]*\.js)"></script>', source):
            with self.subTest(src=src):
                self.assertIn(src, shell)

    def test_firebase_sdk_version_matches_the_page(self):
        # 두 곳에 같은 버전이 적혀 있다. 어긋나면 오프라인에서 엉뚱한 SDK 를 준다.
        source = (WEB / "index.hosting.html").read_text(encoding="utf-8")
        page = set(re.findall(r"/__/firebase/([\d.]+)/", source))
        worker = set(re.findall(r"/__/firebase/([\d.]+)/", self.sw))
        self.assertTrue(page)
        self.assertEqual(page, worker)
        page_scripts = set(re.findall(r'src="(/__/firebase/[^"]+)"', source))
        self.assertEqual(page_scripts, set(self._precache_list("SHELL_OPTIONAL")))

    def test_code_is_served_network_first_so_no_cache_still_means_fresh(self):
        # firebase.json 이 js/css/html 에 no-cache 를 준다. 캐시 우선으로 바꾸면
        # 그 뜻이 무력해진다 — 캐시는 오프라인 사본일 뿐이어야 한다.
        self.assertIn("function networkFirst(", self.sw)
        self.assertIn("networkFirst(request, SHELL_CACHE)", self.sw)
        self.assertIn("function staleWhileRevalidate(", self.sw)
        self.assertIn("staleWhileRevalidate(request, ASSET_CACHE)", self.sw)

    def test_navigation_falls_back_to_the_shell_then_an_offline_page(self):
        self.assertIn('caches.match("/")', self.sw)
        self.assertIn("OFFLINE_HTML", self.sw)
        self.assertIn("연결이 끊겼어요", self.sw)

    def test_activation_drops_only_our_own_stale_caches(self):
        self.assertIn("var VERSION =", self.sw)
        self.assertIn('name.indexOf("archive-") === 0', self.sw)
        self.assertIn("caches.delete(name)", self.sw)
        self.assertIn("self.clients.claim()", self.sw)

    def test_new_version_waits_for_the_reader_instead_of_swapping_itself(self):
        install = re.search(
            r'addEventListener\("install".*?addEventListener\("activate"', self.sw, re.S
        )
        self.assertIsNotNone(install)
        # 설치하자마자 넘어가면 보던 화면이 어긋난다. 설치 단계에 호출이 없어야 한다.
        self.assertNotIn("self.skipWaiting()", install.group(0))
        # 워커를 바꾸는 길은 하나뿐이다 — 사람이 누른 뒤 오는 메시지.
        self.assertEqual(1, self.sw.count("self.skipWaiting()"))
        message = self.sw[self.sw.index('addEventListener("message"'):]
        self.assertIn("self.skipWaiting()", message)
        pwa = (WEB / "pwa.js").read_text(encoding="utf-8")
        self.assertIn('{ type: "SKIP_WAITING" }', pwa)
        self.assertIn("새 버전이 준비됐어요", pwa)


class PwaShellWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hosting = (WEB / "index.hosting.html").read_text(encoding="utf-8")
        cls.local = (WEB / "index.html").read_text(encoding="utf-8")

    def test_hosting_shell_links_the_manifest_and_registers_the_worker(self):
        self.assertIn('<link rel="manifest" href="manifest.webmanifest" />', self.hosting)
        self.assertIn('<script src="pwa.js"></script>', self.hosting)
        self.assertIn('<meta name="theme-color" content="#FBF6EE" />', self.hosting)
        self.assertIn('rel="apple-touch-icon" href="icons/apple-touch-icon.png"', self.hosting)
        self.assertIn('<meta name="mobile-web-app-capable" content="yes" />', self.hosting)

    def test_local_preview_shell_is_deliberately_not_installable(self):
        # site/ 는 data.js 로 대화 전문을 임베드한다. 캐시에 얹으면 개인정보가 디스크에
        # 남는다. 편의를 위해 여기에 PWA 를 켜는 일이 없도록 못을 박는다.
        for forbidden in ("manifest", "pwa.js", "serviceWorker", "sw.js"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.local)

    def test_pwa_toast_is_styled_in_both_themes_shared_stylesheet(self):
        css = (WEB / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".pwa-toast", css)
        self.assertIn(".pwa-toast__action", css)
        # 색을 직접 박으면 다크 모드에서 읽히지 않는다. 토큰만 쓴다.
        block = css[css.index(".pwa-toast {"):css.index(".pwa-toast__action:hover")]
        self.assertNotIn("#", block)

    def test_worker_keeps_the_address_bar_in_step_with_the_theme(self):
        pwa = (WEB / "pwa.js").read_text(encoding="utf-8")
        self.assertIn("THEME_COLORS", pwa)
        self.assertIn('attributeFilter: ["data-theme"]', pwa)
        css = (WEB / "styles.css").read_text(encoding="utf-8")
        dark_bg = re.search(r'data-theme="dark"\]\s*\{\s*--bg:\s*(#[0-9A-Fa-f]{6})', css)
        self.assertIsNotNone(dark_bg)
        self.assertIn(dark_bg.group(1), pwa)


class HostingBuildTests(unittest.TestCase):
    def test_build_copies_every_pwa_file_into_the_deployed_folder(self):
        from scripts import build_hosting

        copied = {dest for _, dest in build_hosting.FILES}
        self.assertLessEqual({"manifest.webmanifest", "sw.js", "pwa.js"}, copied)
        self.assertIn("icons", build_hosting.STATIC_DIRS)

    def test_local_preview_build_leaves_pwa_files_out(self):
        from scripts import build_site

        self.assertNotIn("sw.js", build_site.STATIC_FILES)
        self.assertNotIn("pwa.js", build_site.STATIC_FILES)
        self.assertNotIn("manifest.webmanifest", build_site.STATIC_FILES)
        self.assertNotIn("icons", build_site.STATIC_DIRS)

    def test_worker_scope_requires_it_at_the_site_root(self):
        # 범위가 "/" 이므로 sw.js 는 반드시 루트에 놓여야 한다.
        from scripts import build_hosting

        self.assertIn(("sw.js", "sw.js"), build_hosting.FILES)
        self.assertIn('register("/sw.js", { scope: "/" })',
                      (WEB / "pwa.js").read_text(encoding="utf-8"))


class HostingHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "firebase.json").read_text(encoding="utf-8"))

    def _headers_for(self, hosting: dict, source: str) -> dict[str, str]:
        found = {}
        for rule in hosting.get("headers", []):
            if rule["source"] == source:
                for header in rule["headers"]:
                    found[header["key"]] = header["value"]
        return found

    def test_worker_is_never_cached_by_the_browser(self):
        # 낡은 sw.js 가 캐시에 갇히면 새 배포가 영원히 도달하지 않는다.
        for hosting in self.config["hosting"]:
            with self.subTest(site=hosting["site"]):
                self.assertEqual(
                    "no-cache", self._headers_for(hosting, "/sw.js").get("Cache-Control")
                )

    def test_manifest_is_served_as_a_manifest_and_stays_fresh(self):
        for hosting in self.config["hosting"]:
            with self.subTest(site=hosting["site"]):
                headers = self._headers_for(hosting, "/manifest.webmanifest")
                self.assertIn("application/manifest+json", headers.get("Content-Type", ""))
                self.assertEqual("no-cache", headers.get("Cache-Control"))

    def test_icons_may_be_cached_since_they_rarely_change(self):
        for hosting in self.config["hosting"]:
            with self.subTest(site=hosting["site"]):
                headers = self._headers_for(hosting, "/icons/**")
                self.assertIn("max-age=", headers.get("Cache-Control", ""))


if __name__ == "__main__":
    unittest.main()
