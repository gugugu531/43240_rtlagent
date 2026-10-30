"""Directory-discovered skills and their admission policy."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.config import ROOT
from agent.domain.knowledge.assets import load_assets, read_resource
from agent.domain.knowledge.policy import modes, select_skills, validate_selection


class SkillDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "skill").mkdir()

    def add_skill(self, identity="new-method", *, metadata="", body="A general method.", filename="skill.md"):
        folder = self.root / "skill" / identity
        folder.mkdir(exist_ok=True)
        path = folder / filename
        path.write_text(
            f"---\nname: {identity}\ndescription: A reusable method.\n{metadata}---\n\n{body}\n",
            encoding="utf-8",
        )
        return path

    def load(self):
        return load_assets(skills=True, root=self.root)

    def test_minimal_skill_is_discovered_and_automatically_allowed_without_catalog(self):
        path = self.add_skill()
        assets = self.load()
        self.assertFalse((self.root / "knowledge").exists())
        self.assertEqual(set(assets), {"skills", "cards", "resources"})
        self.assertEqual(assets["cards"], [])
        skill, body = assets["skills"]["new-method"]
        self.assertEqual(skill.id, "new-method")
        self.assertEqual(skill.description, "A reusable method.")
        self.assertEqual(skill.phases, ["generate", "repair"])
        self.assertIsNone(skill.conflict_group)
        self.assertEqual(skill.review_status, "frozen_default_fixed")
        self.assertEqual(body, "A general method.")
        self.assertEqual(assets["resources"], {
            "skill/new-method/skill.md": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
        self.assertEqual(
            select_skills(assets, ["new-method"], ["generate", "repair"], automatic=True),
            (["new-method"], []),
        )

    def test_each_load_sees_body_changes_and_new_directories(self):
        self.add_skill(body="Original method.")
        before = self.load()
        self.add_skill(body="Revised method.")
        self.add_skill("another-method")
        after = self.load()
        self.assertEqual(before["skills"]["new-method"][1], "Original method.")
        self.assertEqual(after["skills"]["new-method"][1], "Revised method.")
        self.assertIn("another-method", after["skills"])
        self.assertNotEqual(before["resources"], after["resources"])

    def test_discovery_is_sorted_without_a_catalog_size_limit(self):
        for number in reversed(range(40)):
            self.add_skill(f"method-{number:02d}")
        assets = self.load()
        self.assertEqual(list(assets["skills"]), [f"method-{number:02d}" for number in range(40)])
        self.assertEqual(list(assets["resources"]), sorted(assets["resources"]))

    def test_only_direct_skill_directories_are_discovered(self):
        (self.root / "skill" / "readme.md").write_text("Not a skill.", encoding="utf-8")
        nested = self.root / "skill" / "container" / "nested"
        nested.mkdir(parents=True)
        (nested / "skill.md").write_text("Not discovered.", encoding="utf-8")
        self.assertEqual(self.load(), {"skills": {}, "cards": [], "resources": {}})

    def test_lowercase_runtime_file_precedes_uppercase_source(self):
        self.add_skill(body="Runtime method.")
        source = self.add_skill(filename="SKILL.md", body="Historical source.")
        # A non-selected historical source need not follow the runtime schema.
        source.write_text("Historical source without frontmatter.", encoding="utf-8")
        assets = self.load()
        self.assertEqual(assets["skills"]["new-method"][1], "Runtime method.")
        self.assertEqual(set(assets["resources"]), {"skill/new-method/skill.md"})

    def test_uppercase_skill_is_discovered_when_lowercase_is_absent(self):
        self.add_skill(filename="SKILL.md")
        assets = self.load()
        self.assertIn("new-method", assets["skills"])
        self.assertEqual(set(assets["resources"]), {"skill/new-method/SKILL.md"})

    def test_invalid_lowercase_file_does_not_fall_back_to_uppercase(self):
        self.add_skill(filename="SKILL.md")
        self.add_skill(body=" ")
        with self.assertRaisesRegex(ValueError, "body must not be empty"):
            self.load()

    def test_invalid_frontmatter_and_body_are_rejected(self):
        path = self.add_skill()
        cases = [
            "No frontmatter.",
            "---\nname: new-method\ndescription: Method.\n",
            "---\n- not-a-mapping\n---\nBody.",
            "---\nname: new-method\ndescription: [unterminated\n---\nBody.",
            "---\nname: new-method\nname: new-method\ndescription: Method.\n---\nBody.",
            "---\nname: new-method\ndescription: Method.\ndescription: Other.\n---\nBody.",
            "---\nname: new-method\n---\nBody.",
            "---\ndescription: Method.\n---\nBody.",
            "---\nname: new-method\ndescription: '   '\n---\nBody.",
            "---\nname: new-method\ndescription: 12\n---\nBody.",
            "---\nname: other-method\ndescription: Method.\n---\nBody.",
            "---\nname: ../new-method\ndescription: Method.\n---\nBody.",
            "---\nname: New_Method\ndescription: Method.\n---\nBody.",
            "---\nname: new-method\ndescription: Method.\n---\n \n\t",
        ]
        for text in cases:
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.load()

    def test_unknown_metadata_invalid_phases_and_status_are_rejected(self):
        for metadata in (
            "unknown: true\n", "id: new-method\n", "version: '1'\n",
            "source: external.md\n", "task_types: [sequential]\n", "subtypes: [counter]\n",
            "phases: []\n", "phases: [check]\n", "phases: [generate, generate]\n",
            "phases: generate\n", "phases: [1]\n", "phases: null\n",
            "phases: [generate]\nphases: [repair]\n",
            "conflict_group: ''\n", "conflict_group: ../external\n",
            "review_status: approved\n", "review_status: null\n",
        ):
            with self.subTest(metadata=metadata):
                self.add_skill(metadata=metadata)
                with self.assertRaises(ValueError):
                    self.load()

    def test_directory_name_must_be_a_valid_skill_name(self):
        self.add_skill("Invalid_Name")
        with self.assertRaises(ValueError):
            self.load()

    def test_symlinked_skill_root_is_rejected(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (self.root / "skill").rmdir()
        (self.root / "skill").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "normal package directory"):
            self.load()

    def test_symlinked_directory_is_rejected_even_for_an_internal_target(self):
        self.add_skill()
        (self.root / "skill" / "linked").symlink_to(
            self.root / "skill" / "new-method", target_is_directory=True,
        )
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.load()

    def test_symlinked_files_and_dangling_symlinks_are_rejected(self):
        path = self.add_skill()
        target = self.root / "source.md"
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.unlink()
        for destination in (target, self.root / "missing.md"):
            with self.subTest(destination=destination):
                path.symlink_to(destination)
                with self.assertRaisesRegex(ValueError, "symlink"):
                    self.load()
                path.unlink()

    def test_lowercase_symlink_never_falls_back_to_uppercase(self):
        path = self.add_skill(filename="SKILL.md")
        (path.parent / "skill.md").symlink_to(path)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.load()

    def test_symlinked_historical_source_is_rejected_even_with_runtime_file(self):
        path = self.add_skill()
        (path.parent / "SKILL.md").symlink_to(path)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.load()

    def test_non_file_skill_resource_is_rejected(self):
        folder = self.root / "skill" / "new-method"
        (folder / "skill.md").mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "normal file"):
            self.load()

    def test_resource_path_rejects_absolute_and_traversal_paths(self):
        self.add_skill()
        for path in ("../outside.md", "/outside.md", "skill/../outside.md", "./skill/new-method/skill.md"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "inside the package"):
                    read_resource(path, root=self.root)

    def test_resource_size_limit_is_preserved(self):
        self.add_skill(body="x" * 32_769)
        with self.assertRaisesRegex(ValueError, "size limit"):
            self.load()

    def test_phase_restrictions_apply_to_automatic_and_explicit_selection(self):
        self.add_skill(metadata="phases: [repair]\n")
        assets = self.load()
        self.assertEqual(select_skills(assets, ["new-method"], ["repair"], automatic=True), (["new-method"], []))
        self.assertEqual(select_skills(assets, ["new-method"], ["generate"], automatic=True), (
            [], [{"id": "new-method", "reason": "unsupported_phase"}],
        ))
        with self.assertRaisesRegex(ValueError, "unsupported_phase"):
            select_skills(assets, ["new-method"], ["generate"])
        for phases in ([], ["check"], ["generate", "generate"]):
            with self.subTest(phases=phases), self.assertRaisesRegex(ValueError, "invalid skill phases"):
                select_skills(assets, [], phases)

    def test_optional_conflict_groups_do_not_conflict_but_declared_groups_do(self):
        self.add_skill("first")
        self.add_skill("second")
        self.assertEqual(select_skills(self.load(), ["first", "second"], ["generate"], automatic=True), (
            ["first", "second"], [],
        ))
        self.add_skill("first", metadata="conflict_group: shared\n")
        self.add_skill("second", metadata="conflict_group: shared\n")
        assets = self.load()
        self.assertEqual(select_skills(assets, ["first", "second"], ["generate"], automatic=True), (
            ["first"], [{"id": "second", "reason": "conflicting_skill"}],
        ))
        with self.assertRaisesRegex(ValueError, "conflicting_skill"):
            select_skills(assets, ["first", "second"], ["generate"])

    def test_selection_still_allows_at_most_two_distinct_skills(self):
        for identity in ("first", "second", "third"):
            self.add_skill(identity)
        for identities in (["first", "second", "third"], ["first", "first"]):
            with self.subTest(identities=identities), self.assertRaisesRegex(ValueError, "at most two distinct"):
                select_skills(self.load(), identities, ["generate"], automatic=True)

    def test_packaged_statuses_are_preserved_and_interface_skill_is_discovered(self):
        assets = load_assets(skills=True, root=ROOT)
        for identity in ("rtl-width-signed-arithmetic", "rtl-combinational-completeness", "rtl-fsm-state-output"):
            with self.subTest(identity=identity):
                self.assertEqual(assets["skills"][identity][0].review_status, "frozen_rejected_fixed_ab")
                self.assertEqual(select_skills(assets, [identity], ["generate"], automatic=True), (
                    [], [{"id": identity, "reason": "rejected_fixed_ab"}],
                ))
                with self.assertRaisesRegex(ValueError, "rejected_fixed_ab"):
                    select_skills(assets, [identity], ["generate"])
        for identity in ("rtl-sequential-state-update-v3", "rtl-behavior-check-keycases"):
            with self.subTest(identity=identity):
                self.assertEqual(assets["skills"][identity][0].review_status, "frozen_candidate_not_default")
                self.assertEqual(select_skills(assets, [identity], ["generate"], automatic=True), (
                    [], [{"id": identity, "reason": "not_approved_for_automatic_selection"}],
                ))
                self.assertEqual(select_skills(assets, [identity], ["generate"]), ([identity], []))
        self.assertEqual(select_skills(assets, ["rtl-sequential-state-update"], ["generate"], automatic=True), (
            ["rtl-sequential-state-update"], [],
        ))
        identity = "rtl-module-interface-contract"
        self.assertEqual(select_skills(assets, [identity], ["generate", "repair"], automatic=True), ([identity], []))
        self.assertIn(f"skill/{identity}/SKILL.md", assets["resources"])
        self.assertNotIn("knowledge/catalog.json", assets["resources"])
        with self.assertRaisesRegex(ValueError, "conflicting_skill"):
            select_skills(assets, ["rtl-sequential-state-update", "rtl-sequential-state-update-v3"], ["repair"])

    def test_skill_modes_default_to_on_and_respect_explicit_modes(self):
        self.assertEqual(modes(), ("on", "off"))
        self.assertEqual(modes("off"), ("off", "off"))
        self.assertEqual(modes("shadow"), ("shadow", "off"))
        with patch("agent.domain.knowledge.assets.load_assets") as loader:
            validate_selection({})
            validate_selection({"skill_mode": "off", "skill_ids": ["not-loaded"]})
            loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
