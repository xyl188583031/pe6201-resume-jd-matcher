"""Streamlit UI for the Graduate Resume-JD Matcher.

    streamlit run app.py

Interface and serving layer: Built (PS section 5), no cloud hosting. Model
inference: Rented (OpenRouter). Retrieval: Built (local Chroma / numpy store).

Three operational rules are enforced here rather than left to the user:

1. The prototype banner is always visible (PS section 8, Risks 3 and 4).
2. Inputs are processed in memory and never written to disk. The run log records
   hashes and lengths, not text.
3. Prefill values are shown as editable *suggestions* with a per-field
   confidence. Nothing is written into the simulated form until the user clicks
   Fill, and a field below the abstention threshold is withheld with a reason.

The UI deliberately shows the raw numbers - both confidence components, the
retrieved chunk ids, the abstention reason - because the prototype's whole claim
is that its abstention behaviour is inspectable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import config  # noqa: E402
from src.config import ConfidenceConfig  # noqa: E402
from src.llm.client import OpenRouterClient  # noqa: E402
from src.pipeline.pdf import extract_pdf_text  # noqa: E402
from src.pipeline.prefill import load_form_schema  # noqa: E402
from src.pipeline.runner import CONDITION_LABELS, run_case  # noqa: E402
from src.retrieval.store import build_knowledge_base  # noqa: E402

st.set_page_config(page_title="Graduate Resume-JD Matcher", page_icon="📄", layout="wide")

SAMPLES_DIR = REPO_ROOT / "data" / "samples"
CASES_PATH = REPO_ROOT / "data" / "cases" / "cases.json"
DEMO_FORM = REPO_ROOT / "src" / "ui" / "demo_form.html"
REPORT_PATH = config.path("report_md")


# --------------------------------------------------------------------- helpers


@st.cache_resource(show_spinner=False)
def _kb(embedding_backend: str):
    return build_knowledge_base(embedding_backend=embedding_backend)


def _sample_names() -> list[str]:
    if not SAMPLES_DIR.exists():
        return []
    return sorted(p.name for p in SAMPLES_DIR.glob("*_resume.txt"))


def _read_sample(name: str) -> str:
    path = SAMPLES_DIR / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _sample_jd_for(resume_name: str) -> str:
    return _read_sample(resume_name.replace("_resume.txt", "_jd.txt"))


def _load_sample_into_fields() -> None:
    """Dropdown -> text areas, via a callback.

    A text_area that carries a `key` reads its value from session_state on every
    rerun and IGNORES the `value=` argument, so `value=_read_sample(chosen)` only
    ever worked on the very first render. Pushing the sample into the session keys
    in the selectbox's on_change keeps the two widgets in sync.
    """
    chosen = st.session_state.get("sample_resume", "(none)")
    if chosen == "(none)":
        st.session_state["resume_text"] = ""
        st.session_state["jd_text"] = ""
    else:
        st.session_state["resume_text"] = _read_sample(chosen)
        st.session_state["jd_text"] = _sample_jd_for(chosen)


def _render_demo_form(payload: dict) -> None:
    if not DEMO_FORM.exists():
        st.info("Demo form template not found at src/ui/demo_form.html")
        return
    html = DEMO_FORM.read_text(encoding="utf-8")
    html = html.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    st.components.v1.html(html, height=760, scrolling=True)


def _demo_payload(result, schema: dict) -> dict:
    """Shape the prefill bundle into what the browser form expects."""
    if result is None or result.prefill is None:
        return {}
    schema_by_name = {f["name"]: f for f in schema.get("fields", [])}
    fields = []
    for item in result.prefill.as_dict()["fields"]:
        meta = schema_by_name.get(item["name"], {})
        fields.append(
            {
                "name": item["name"],
                "label": meta.get("label", item["label"]),
                "required": bool(meta.get("required", False)),
                "is_list": bool(item["is_list"]),
                "status": item["status"],
                "value": item["value"],
                "confidence": item["confidence"],
                "reason": item["reason"],
            }
        )
    return {
        "title": "Application form (simulated)",
        "subtitle": f"Condition {result.condition} - {CONDITION_LABELS.get(result.condition, '')}. "
        "Suggestions only; nothing is submitted.",
        "fields": fields,
    }


# ------------------------------------------------------------------- sidebar

with st.sidebar:
    st.header("Configuration")

    api_key = st.text_input(
        "OpenRouter API key",
        type="password",
        placeholder="sk-or-v1-...",
        help="Read from OPENROUTER_API_KEY if left blank. Never written to disk.",
    )
    condition = st.radio(
        "Condition",
        options=["C", "B", "A"],
        format_func=lambda c: f"{c} - {CONDITION_LABELS[c]}",
        index=0,
        help="A is the non-AI TF-IDF baseline. B is prompt-only. C adds RAG.",
    )
    top_k = st.slider("Retrieved chunks (condition C)", 1, 8, int(config.get("retrieval", "top_k", default=4)))

    st.divider()
    cfg = ConfidenceConfig.load()
    st.caption(
        f"Abstention threshold: **{cfg.threshold}**  \n"
        f"Confidence = {cfg.w_retrieval} x retrieval + {cfg.w_llm_self} x model self-report  \n"
        f"Declines if either component falls below {cfg.threshold}."
    )
    st.divider()
    st.caption(
        "**Privacy.** Inputs are processed in memory only. Nothing is uploaded to us, "
        "nothing is stored, and no field is ever submitted to a real site."
    )
    with st.expander("Retrieval backend"):
        try:
            st.json(_kb("auto").describe())
        except Exception as exc:  # noqa: BLE001 - the UI must still load
            st.warning(f"Knowledge base unavailable: {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------- header

st.title("📄 Graduate Resume-JD Matcher")
st.caption("RAG-grounded tailoring assistant with an abstention rule that refuses to invent experience.")

st.warning(
    f"**{config.banner()}**\n\n"
    "Synthetic and in-memory data only. Prefilled values are editable suggestions, "
    "applied only when you click Fill. " + config.non_use_notice()
)

tab_run, tab_form, tab_eval = st.tabs(["Run a match", "Simulated form", "Evaluation report"])


# ------------------------------------------------------------------------- run

with tab_run:
    left, right = st.columns(2)

    with left:
        st.subheader("1 . Candidate resume")
        samples = _sample_names()
        st.selectbox(
            "Load a synthetic sample",
            ["(none)"] + samples,
            key="sample_resume",
            on_change=_load_sample_into_fields,
        )
        uploaded = st.file_uploader("...or upload a PDF", type=["pdf"])
        # No `value=`: the widget's value lives in session_state under this key.
        st.session_state.setdefault("resume_text", "")
        pasted_resume = st.text_area(
            "...or paste resume text", height=180, key="resume_text"
        )

        resume_text = pasted_resume or ""
        pdf_note = None
        if uploaded is not None:
            extracted = extract_pdf_text(uploaded.getvalue())
            pdf_note = extracted
            resume_text = extracted.text or resume_text

        if pdf_note is not None:
            if pdf_note.ok:
                st.success(f"Parsed {pdf_note.pages} page(s) with `{pdf_note.engine}`.")
            else:
                st.error("Could not extract usable text from that PDF.")
            for warning in pdf_note.warnings[:3]:
                st.caption(f"- {warning}")

    with right:
        st.subheader("2 . Job description")
        st.caption("Treated as untrusted text: instruction-like patterns are redacted before it reaches the model.")
        st.session_state.setdefault("jd_text", "")
        jd_text = st.text_area(
            "Paste the job description", height=330, key="jd_text",
            placeholder="Paste the posting here...",
        )

    run = st.button("Run match", type="primary", use_container_width=True)

    if run:
        if not resume_text.strip():
            st.error("Provide a resume: upload a PDF, paste text, or load a sample.")
        elif not jd_text.strip():
            st.error("Provide a job description.")
        else:
            client = OpenRouterClient(api_key=api_key or None)
            if client.offline:
                st.info(
                    "Running **offline**: no API key, so conditions B and C are served by the "
                    "deterministic stub. Condition A is fully real. Set a key for model behaviour."
                )
            with st.spinner("Parsing, retrieving, scoring..."):
                try:
                    kb = _kb("auto") if condition == "C" else None
                    result = run_case(
                        case_id="ui",
                        resume_text=resume_text,
                        jd_text=jd_text,
                        condition=condition,
                        client=client,
                        kb=kb,
                        cfg=cfg,
                        form_schema=load_form_schema(),
                    )
                    st.session_state["result"] = result
                except Exception as exc:  # noqa: BLE001 - surface, never crash the app
                    st.exception(exc)

    result = st.session_state.get("result")
    if result is not None:
        st.divider()
        head = st.columns(4)
        head[0].metric("Match score", f"{result.match_score}/100")
        head[1].metric("Confidence", f"{float(result.assessment.combined):.2f}")
        head[2].metric("Threshold", f"{float(result.assessment.threshold):.2f}")
        head[3].metric("Chunks retrieved", len(result.retrieved_chunk_ids))

        if result.abstained:
            st.error(
                "**System declined to suggest content for this case.**\n\n"
                + "\n".join(f"- {reason}" for reason in result.assessment.reasons)
            )
        else:
            st.success("Evidence cleared the threshold; suggestions below are grounded in the resume.")

        with st.expander("Confidence breakdown", expanded=result.abstained):
            st.json(result.assessment.to_payload())
            st.caption(
                "Condition A has no model component and condition B has no retrieval component, "
                "so confidence is the weighted mean over the components that exist. "
                "Substituting zero for an absent component would make those conditions abstain "
                "structurally, which would be an artefact rather than a result."
            )

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Matched skills** (evidenced by the resume)")
            st.write(", ".join(result.matched_skills) or "_(none)_")
            st.markdown("**Missing requirements**")
            st.write(", ".join(result.missing_skills) or "_(none)_")
        with col_b:
            st.markdown("**JD requirements extracted**")
            st.write(", ".join(result.jd_skills) or "_(none)_")
            if result.retrieval:
                st.markdown("**Retrieved chunks** (provenance)")
                for hit in result.retrieval.hits:
                    st.caption(f"`{hit.chunk_id}` score {hit.score:.2f} - {hit.text[:80]}...")

        st.markdown("**Suggestions**")
        for item in result.suggestions:
            st.markdown(f"- {item}")

        if result.notes:
            with st.expander("Run notes"):
                for note in result.notes:
                    st.caption(f"- {note}")

        st.divider()
        st.subheader("3 . Prefill suggestions")
        bundle = result.prefill
        if bundle is None:
            st.info("No prefill produced.")
        else:
            st.caption(
                f"{bundle.suggestions_offered} offered, {bundle.suggestions_withheld} withheld. "
                "Nothing is applied automatically."
            )
            st.dataframe(
                [
                    {
                        "field": f.label,
                        "status": f.status,
                        "confidence": f.confidence,
                        "suggested value": f.value or "-",
                        "note": f.reason,
                    }
                    for f in bundle.fields
                ],
                use_container_width=True,
                hide_index=True,
            )
            _render_demo_form(_demo_payload(result, load_form_schema()))


# -------------------------------------------------------------------- form tab

with tab_form:
    st.subheader("Simulated recruitment form")
    st.caption(
        "Click a field to see its suggestion, edit it if you want, then click Fill. "
        "A field below the confidence threshold shows a warning instead of a value."
    )
    existing = st.session_state.get("result")
    if existing is None:
        st.info("Showing the built-in demo. Run a match first to drive the form with real output.")
        _render_demo_form({})
    else:
        _render_demo_form(_demo_payload(existing, load_form_schema()))


# -------------------------------------------------------------------- eval tab

with tab_eval:
    st.subheader("Evaluation report")
    if REPORT_PATH.exists():
        st.caption(f"From `{REPORT_PATH.relative_to(REPO_ROOT)}`")
        st.markdown(REPORT_PATH.read_text(encoding="utf-8"))
    else:
        st.info(
            "No report yet. Generate one with:\n\n"
            "```\npython -m data.synthetic_generator.generate_cases\n"
            "python eval/run_eval.py --offline\n```"
        )
    cases_path = CASES_PATH
    if cases_path.exists():
        payload = json.loads(cases_path.read_text(encoding="utf-8"))
        with st.expander(f"Test set ({len(payload.get('cases', []))} synthetic cases)"):
            st.json(payload.get("meta", {}))
            st.caption(
                "Ground truth lives in `data/cases/ground_truth.csv` and is written before any "
                "model call. The pipeline never receives it."
            )
