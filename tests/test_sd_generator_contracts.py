"""백엔드와 무관해야 하는 계약들 — ComfyUI 이식 후에도 그대로여야 하는 것만 본다.

메타데이터 왕복(EXIF/사이드카), 스프라이트 조회, 배경 재사용 판정은 어느 백엔드로 그렸든 같아야
한다. 이식하면서 이 셋이 조용히 깨지면 기존 자산(왓슨·로이·가스주)을 못 찾거나, 표정 생성이
베이스 조건을 잃는다. ComfyUI 없이 돈다.

실행: python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.sd_generator as sg  # noqa: E402


class MetaRoundTrip(unittest.TestCase):
    """A1111 parameters 문자열 <-> dict 왕복. WebUI PNG Info 가 읽는 형식이라 깨지면 안 된다."""

    def setUp(self):
        self.meta = {
            "prompt": "a girl, victorian blouse",
            "negative_prompt": "lowres, bad anatomy",
            "steps": 20,
            "sampler_name": "DPM++ 2M Karras",
            "cfg_scale": 7,
            "seed": 198054123,
            "size": [728, 1104],
            "sd_model_checkpoint": "neverendingDreamNED_v122BakedVae.safetensors",
        }

    def test_roundtrip_preserves_render_conditions(self):
        text = sg.a1111_parameters(self.meta)
        back = sg.parse_a1111_parameters(text)
        self.assertEqual(back.get("prompt"), self.meta["prompt"])
        self.assertEqual(back.get("negative_prompt"), self.meta["negative_prompt"])
        self.assertEqual(int(back.get("steps")), 20)
        self.assertEqual(int(back.get("seed")), 198054123)
        self.assertEqual(back.get("sampler_name"), "DPM++ 2M Karras")

    def test_exif_written_and_read_back(self):
        from PIL import Image
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "x.webp")
            sg._save_with_meta(Image.new("RGB", (64, 64), (128, 128, 128)), path, self.meta)
            got = sg.read_image_meta(path)
            self.assertEqual(got.get("seed"), self.meta["seed"])
            self.assertEqual(got.get("sd_model_checkpoint"), self.meta["sd_model_checkpoint"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SpriteLookup(unittest.TestCase):
    """이름/표정으로 기존 스프라이트를 찾는 경로. 재활용(reuse-first)이 여기에 걸려 있다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = sg.SD_NPC_DIR
        sg.SD_NPC_DIR = self.tmp
        d = os.path.join(self.tmp, "watson")
        os.makedirs(d)
        for fname in ("neutral.webp", "smile.webp", "var_armored.webp", "var_casual.webp"):
            with open(os.path.join(d, fname), "wb") as f:
                f.write(b"\x00")

    def tearDown(self):
        sg.SD_NPC_DIR = self.orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_finds_existing_expression(self):
        self.assertTrue(sg.find_npc_sprite("watson", "neutral"))
        self.assertTrue(sg.find_npc_sprite("Watson", "smile"))

    def test_missing_expression_falls_back_to_neutral(self):
        # VN 표시에는 무엇이든 한 장이 필요하다 — 없는 표정은 neutral 로 떨어지는 것이 설계다
        self.assertEqual(sg.find_npc_sprite("watson", "angry"),
                         "/static/portraits/npc/watson/neutral.webp")

    def test_unknown_character_returns_none(self):
        self.assertIsNone(sg.find_npc_sprite("전혀없는사람", "neutral"))

    def test_variants_list_only_var_files(self):
        # 변형(var_*)만 나열한다. 표정(neutral/smile)은 변형이 아니다
        feats = sorted(v["feature"] for v in sg.list_npc_variants("watson"))
        self.assertEqual(feats, ["armored", "casual"])

    def test_seed_is_stable_per_name(self):
        # 같은 인물은 표정이 달라도 같은 시드여야 얼굴이 유지된다
        self.assertEqual(sg._npc_seed("watson"), sg._npc_seed("watson"))
        self.assertNotEqual(sg._npc_seed("watson"), sg._npc_seed("holmes"))


class BackgroundReuse(unittest.TestCase):
    """비슷한 배경을 다시 그리지 않고 재활용하는 판정."""

    def test_conflicting_attributes_block_reuse(self):
        day = sg._bg_tokens_of("a sunny courtyard, day")
        night = sg._bg_tokens_of("a courtyard at night, moonlight")
        self.assertTrue(sg._bg_conflict(sg._bg_attrs(day), sg._bg_attrs(night)))

    def test_same_scene_does_not_conflict(self):
        a = sg._bg_attrs(sg._bg_tokens_of("a stone corridor, torches"))
        b = sg._bg_attrs(sg._bg_tokens_of("a stone corridor with torches"))
        self.assertFalse(sg._bg_conflict(a, b))


class CheckpointRouting(unittest.TestCase):
    def test_person_and_scene_use_different_checkpoints(self):
        self.assertEqual(sg.checkpoint_for("sprite"), sg.PERSON_CHECKPOINT)
        self.assertEqual(sg.checkpoint_for("portrait"), sg.PERSON_CHECKPOINT)
        self.assertEqual(sg.checkpoint_for("background"), sg.SCENE_CHECKPOINT)

    def test_spec_carries_checkpoint_and_size(self):
        # ComfyUI 에는 "현재 체크포인트" 가 없으므로 spec 이 들고 가야 한다
        spec = sg._build_spec("sprite", "p", "")
        self.assertEqual(spec.checkpoint, sg.PERSON_CHECKPOINT)
        self.assertEqual((spec.width, spec.height), (728, 1104))
        bg = sg._build_spec("background", "p", "")
        self.assertEqual(bg.checkpoint, sg.SCENE_CHECKPOINT)
        self.assertEqual((bg.width, bg.height), (896, 512))

    def test_style_compensation_by_bias(self):
        self.assertIn("natural skin", sg.style_compensation("aniverse_thxEd14Pruned.safetensors"))
        self.assertIn("anime", sg.style_compensation("chilloutmix_NiPrunedFp32Fix.safetensors"))
        self.assertEqual(sg.style_compensation("dreamshaper_8.safetensors"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
