import pytest

from agent_core.resources.folder import FolderResources


def test_reads_a_file_relative_to_the_root(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.md").write_text("hello")
    folder = FolderResources(tmp_path)
    assert folder.read("a/b.md") == "hello"
    assert folder.exists("a/b.md") and not folder.exists("a/c.md")


def test_a_missing_file_error_names_the_path(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"skills/x/SKILL\.md"):
        FolderResources(tmp_path).read("skills/x/SKILL.md")


def test_folder_refuses_a_path_outside_its_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret").write_text("s")
    folder = FolderResources(root)
    with pytest.raises(ValueError):
        folder.read("../secret")
    with pytest.raises(ValueError):
        folder.exists("../secret")
    with pytest.raises(ValueError):
        folder.read(str(tmp_path / "secret"))


def test_folder_refuses_a_symlink_that_leaves_its_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret").write_text("s")
    (root / "link").symlink_to(tmp_path / "secret")
    with pytest.raises(ValueError):
        FolderResources(root).read("link")
