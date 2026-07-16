"""Regression tests for the _find_all_skills discovery cache (#58985 salvage).

Covers the cache-signature fix layered on the cherry-picked contributor
commit: the original keyed the cache on the max mtime of only the top-level
scan directories, so adding/removing a skill inside a category subdirectory
could serve a stale list until the TTL expired. The signature now covers every
directory traversed by skill discovery plus the disabled set, while a short TTL
bounds in-place SKILL.md content-edit staleness.
"""

import os

import pytest

import tools.skills_tool as st


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch, tmp_path):
    """Clear the module cache and point discovery at a temporary skill root."""
    st._SKILLS_CACHE.clear()
    monkeypatch.setattr(st, "_skills_dir", lambda: tmp_path / "skills")
    monkeypatch.setattr(
        "agent.skill_utils.get_external_skills_dirs", lambda: []
    )
    monkeypatch.setattr(st, "_get_disabled_skill_names", lambda: set())
    yield
    st._SKILLS_CACHE.clear()


def _write_skill(root, category, name, description="a skill"):
    skill_dir = root / "skills" / category / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n",
        encoding="utf-8",
    )
    return skill_dir


def test_cache_hit_serves_copies_not_cache_objects(tmp_path):
    """Mutating one caller's result must not poison cached metadata."""
    _write_skill(tmp_path, "cat-a", "skill-one")
    first = st._find_all_skills()
    assert [skill["name"] for skill in first] == ["skill-one"]

    first[0]["enabled"] = False
    first.append({"name": "junk"})

    second = st._find_all_skills()
    assert [skill["name"] for skill in second] == ["skill-one"]
    assert "enabled" not in second[0], "cache poisoned by caller mutation"
    assert second is not first


def test_nested_category_skill_add_invalidates(tmp_path):
    """Adding a skill under an existing category invalidates immediately."""
    _write_skill(tmp_path, "cat-a", "skill-one")
    first = st._find_all_skills()
    assert [skill["name"] for skill in first] == ["skill-one"]

    root = tmp_path / "skills"
    root_stat = root.stat()
    _write_skill(tmp_path, "cat-a", "skill-two")
    # Freeze the root mtime so the category/skill directory signature must move.
    os.utime(root, (root_stat.st_atime, root_stat.st_mtime))

    names = sorted(skill["name"] for skill in st._find_all_skills())
    assert names == ["skill-one", "skill-two"], (
        "category-nested skill add must invalidate the cache"
    )


def test_cache_invalidates_below_nested_categories(tmp_path):
    """Changes below a top-level category must be represented recursively."""
    first_path = _write_skill(
        tmp_path, "mlops/evaluation", "skill-one"
    )
    first = st._find_all_skills()
    assert [skill["name"] for skill in first] == ["skill-one"]

    root = tmp_path / "skills"
    top_category = root / "mlops"
    root_stat = root.stat()
    top_stat = top_category.stat()
    _write_skill(tmp_path, "mlops/evaluation", "skill-two")
    # Preserve root/top-category mtimes. The deeper evaluation directory and
    # new skill path must still invalidate the recursive signature.
    os.utime(root, (root_stat.st_atime, root_stat.st_mtime))
    os.utime(top_category, (top_stat.st_atime, top_stat.st_mtime))
    assert first_path.exists()

    names = sorted(skill["name"] for skill in st._find_all_skills())
    assert names == ["skill-one", "skill-two"]


def test_disabled_set_change_invalidates(tmp_path, monkeypatch):
    """Config-only disabled-set changes invalidate without filesystem writes."""
    _write_skill(tmp_path, "cat-a", "skill-one")
    _write_skill(tmp_path, "cat-a", "skill-two")
    names = sorted(skill["name"] for skill in st._find_all_skills())
    assert names == ["skill-one", "skill-two"]

    monkeypatch.setattr(st, "_get_disabled_skill_names", lambda: {"skill-two"})
    names = sorted(skill["name"] for skill in st._find_all_skills())
    assert names == ["skill-one"], "disabled-set change must invalidate the cache"


def test_ttl_expiry_forces_rescan(tmp_path, monkeypatch):
    """The TTL bounds content edits invisible to directory metadata."""
    skill_dir = _write_skill(
        tmp_path, "cat-a", "skill-one", "old description"
    )
    first = st._find_all_skills()
    assert first[0]["description"] == "old description"

    category = tmp_path / "skills" / "cat-a"
    root = tmp_path / "skills"
    stats = {path: path.stat() for path in (root, category, skill_dir)}
    (skill_dir / "SKILL.md").write_text(
        "---\nname: skill-one\ndescription: new description\n---\n# skill-one\n",
        encoding="utf-8",
    )
    for path, stat in stats.items():
        os.utime(path, (stat.st_atime, stat.st_mtime))

    assert st._find_all_skills()[0]["description"] == "old description"

    monkeypatch.setattr(st, "_SKILLS_CACHE_TTL_SECONDS", 0.0)
    assert st._find_all_skills()[0]["description"] == "new description"


def test_disabled_and_full_views_cached_separately(tmp_path, monkeypatch):
    _write_skill(tmp_path, "cat-a", "skill-one")
    _write_skill(tmp_path, "cat-a", "skill-two")
    monkeypatch.setattr(st, "_get_disabled_skill_names", lambda: {"skill-two"})

    filtered = sorted(skill["name"] for skill in st._find_all_skills())
    everything = sorted(
        skill["name"] for skill in st._find_all_skills(skip_disabled=True)
    )
    assert filtered == ["skill-one"]
    assert everything == ["skill-one", "skill-two"]
