import pytest

from agent_core.core.settings import load_settings
from agent_core.core.templates import TemplateError, render
from support import FolderSource


@pytest.fixture
def render_text(instance):
    """Render `text` against the fixture instance; the settings are the fixture's with `alpha.yaml` layered over."""
    settings = load_settings(instance, [instance.root / "config" / "alpha.yaml"])

    def render_it(text, *, file="nodes/example.md", inputs=None, session=None, values=None):
        return render(
            text, file=file, settings=settings, inputs=inputs or {}, session=session or {},
            values=values or {}, resources=FolderSource(instance.root),
        )

    return render_it


@pytest.fixture
def render_refresh(instance, render_text):
    node = instance.nodes["refresh"]
    return lambda **kwargs: render_text(node.body, file=node.file, **kwargs)


def test_include_pulled_in_and_single_braces_left_alone(render_refresh):
    text = render_refresh()
    assert "no force-push" in text and "{count}" in text


def test_include_inside_an_include(render_text):
    assert render_text("{{include includes/nested.md}}").startswith("Nested:")
    assert "no force-push" in render_text("{{include includes/nested.md}}")


def test_include_that_includes_itself_names_the_loop(render_text):                    # TPL-2b
    with pytest.raises(TemplateError) as e:
        render_text("{{include includes/loop_a.md}}")
    assert str(e.value) == "includes/loop_a.md includes itself (loop_a.md → loop_b.md → loop_a.md)"


def test_missing_input_reads_not_given_and_unset_values_read_not_set(render_refresh):  # TPL-5, TPL-8
    text = render_refresh()
    assert "Sources to update: not given." in text and "Branch: not set." in text


def test_values_show_when_filled_again(render_refresh):                                # TPL-4: filled when a run starts
    text = render_refresh(inputs={"sources": "polars"}, session={"branch": "refresh/alpha"})
    assert "Sources to update: polars." in text and "Branch: refresh/alpha." in text


def test_a_working_value_shows_through_a_node_placeholder(render_text):               # TPL-1
    assert render_text("Progress so far: {{node.progress}}.", values={"progress": "3 of 8"}) == "Progress so far: 3 of 8."
    assert render_text("Progress so far: {{node.progress}}.") == "Progress so far: not set."


def test_settings_are_filled_in(render_refresh):
    assert "Corpus: alpha in /tmp/spike-corpus-alpha." in render_refresh()


def test_secret_is_filled_masked(render_refresh):
    text = render_refresh()
    assert "not-a-real-token" not in text and "Token: **********." in text


def test_unknown_settings_placeholder_names_placeholder_and_file(render_text):         # TPL-6b
    with pytest.raises(TemplateError) as e:
        render_text("Repo: {{settings.CORPUS_REPOO}}", file="nodes/refresh.md")
    assert "settings.CORPUS_REPOO" in str(e.value) and "nodes/refresh.md" in str(e.value)


def test_unknown_placeholder_in_an_include_names_the_include(render_text, broken):
    broken("includes/safety.md", "Oops {{settings.NOPE}}")
    with pytest.raises(TemplateError) as e:
        render("{{include includes/safety.md}}", file="nodes/x.md", settings=None,
               inputs={}, session={}, values={}, resources=FolderSource(broken.root))
    assert "settings.NOPE" in str(e.value) and "includes/safety.md" in str(e.value)


def test_settings_placeholder_without_settings_is_an_error(broken):
    with pytest.raises(TemplateError) as e:
        render("{{settings.CORPUS_NAME}}", file="nodes/x.md", settings=None,
               inputs={}, session={}, values={}, resources=FolderSource(broken.root))
    assert "settings.CORPUS_NAME" in str(e.value) and "nodes/x.md" in str(e.value)


def test_missing_include_names_the_path_and_the_file(render_text):
    with pytest.raises(TemplateError) as e:
        render_text("{{include includes/nope.md}}", file="nodes/refresh.md")
    assert "includes/nope.md" in str(e.value) and "nodes/refresh.md" in str(e.value)


def test_nothing_else_is_interpreted(render_text):                                    # TPL-3
    text = "{x} {{other.name}} {{ settings }} {{input}} ${HOME}"
    assert render_text(text) == text


def test_a_filled_value_is_not_interpreted_again(render_text):
    assert render_text("{{input.a}}", inputs={"a": "{{include includes/safety.md}} {{node.b}}"}) == (
        "{{include includes/safety.md}} {{node.b}}"
    )
