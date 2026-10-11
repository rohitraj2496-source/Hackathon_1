"""Haq web UI with the agent stubbed out, for screenshots and UI work. Makes NO model or web calls.

    .venv/bin/python scripts/ui_stub_server.py      # serves http://127.0.0.1:8001

The fake run emits the same live events as the real agent (including a website failure that is
recovered from another official source), then pauses until POST /stub/release, so the working screen
can be captured mid-run. Results include confirmed and "check needed" cards.
"""
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ.update(NEATLOGS_API_KEY="", ANTHROPIC_API_KEY="stub-no-calls",
                  HAQ_STATE_FILE=os.path.join(tempfile.mkdtemp(prefix="haq-stub-"), "state.json"))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import app as appmod  # noqa: E402
from haq import agent, intake, present, state  # noqa: E402

release = threading.Event()


def fake_run(hid, resume=True):
    h = state.get(hid)
    run = h["runs"][-1] if h["runs"] and h["runs"][-1]["status"] != "done" else state.start_run(hid)
    rid = run["id"]

    def ev(t, pause=0.35, **d):
        state.add_event(hid, rid, t, **d)
        time.sleep(pause)

    ev("understood", members=3)
    ev("planned", schemes=4)
    ev("checking", scheme_id="pm_kisan", from_cache=False)
    ev("recovered", scheme_id="pm_kisan", requested="https://pmkisan.gov.in/",
       served_by="https://www.myscheme.gov.in/schemes/pm-kisan", fell_back=True)
    ev("scheme_done", scheme_id="pm_kisan", outcome="confirmed")
    ev("checking", scheme_id="up_widow_pension", from_cache=True)
    ev("scheme_done", scheme_id="up_widow_pension", outcome="likely")
    ev("checking", scheme_id="pmay_g", from_cache=False)
    ev("checking", scheme_id="pmsby", from_cache=True)
    release.wait(timeout=120)          # hold here so the working screen can be captured
    ev("scheme_done", scheme_id="pmay_g", outcome="likely")
    ev("scheme_done", scheme_id="pmsby", outcome="confirmed")
    ev("writing")

    def card(sid, emoji, name, member, ben, val, ver, chk, docs, counts, where, url):
        return dict(scheme_id=sid, emoji=emoji, name_hi=name, name_en=name, member=member, benefit_hi=ben,
                    annual_value_inr=val, verification=ver, check_needed=chk, counts_toward_total=counts,
                    counts_toward_likely_total=(not counts) and val > 0, already_receiving=False,
                    documents_hi=docs, where_to_apply_hi=where, apply_url=url, official_url=url,
                    unconfirmed_rules=[], rules_checked=[], assumptions_hi="")
    csc = "नज़दीकी जन सेवा केंद्र (CSC) या ब्लॉक कार्यालय में आवेदन करें।"
    result = {
        "total_missing_inr_per_year": 6000, "likely_extra_inr_per_year": 12000,
        "summary_hi": "आपका परिवार हर साल छह हज़ार रुपये पक्का नहीं ले रहा है। दादी को विधवा पेंशन भी मिल सकती है, "
                      "उसके लिए आय सीमा की जाँच करवाएँ। कागज़ लेकर जन सेवा केंद्र जाइए।",
        "cards": [
            card("pm_kisan", "🌾", "पीएम किसान", "father", "हर साल ₹6,000, तीन किस्तों में सीधे बैंक खाते में।", 6000,
                 "confirmed", [], ["आधार कार्ड", "बैंक पासबुक", "खतौनी (ज़मीन के कागज़)"], True, csc,
                 "https://pmkisan.gov.in/"),
            card("up_widow_pension", "🙏", "निराश्रित महिला पेंशन", "grandmother", "हर महीने ₹1,000 पेंशन, सीधे बैंक खाते में।",
                 12000, "likely", ["income_limit"], ["आधार कार्ड", "पति का मृत्यु प्रमाण पत्र", "आय प्रमाण पत्र", "बैंक पासबुक"],
                 False, csc, "https://sspy-up.gov.in/"),
            card("pmay_g", "🏠", "पीएम आवास (ग्रामीण)", "household", "पक्का घर बनाने के लिए ₹1.2 लाख की मदद।", 0, "likely",
                 ["house", "area"], ["आधार कार्ड", "राशन कार्ड", "बैंक पासबुक"], False, csc, "https://pmayg.dord.gov.in/"),
            card("pmsby", "🦺", "PMSBY", "father", "सिर्फ़ ₹20 सालाना में ₹2 लाख का दुर्घटना बीमा।", 0, "confirmed", [],
                 ["आधार कार्ड", "बैंक खाता", "मोबाइल नंबर"], False, "अपने बैंक की शाखा में फ़ॉर्म भरें।",
                 "https://jansuraksha.gov.in/"),
        ]}
    ev("done", pause=0)
    state.update_run(hid, rid, lambda r: r.update(result=result, status="done", stage="done"))


EN = {
    "summary": "Your family is missing ₹6,000 a year for sure. Grandmother may also get the widow pension — "
               "get the income limit checked. Take your documents to the Common Service Centre.",
    "benefit": ["₹6,000 every year in three instalments, straight to your bank account.",
                "₹1,000 pension every month, straight to the bank.",
                "₹1.2 lakh to help build a pucca house.",
                "₹2 lakh accident cover for just ₹20 a year."],
    "docs": [["Aadhaar card", "Bank passbook", "Khatauni (land record)"],
             ["Aadhaar card", "Husband's death certificate", "Income certificate", "Bank passbook"],
             ["Aadhaar card", "Ration card", "Bank passbook"],
             ["Aadhaar card", "Bank account", "Mobile number"]],
    "where": ["Apply at the nearest Common Service Centre (CSC) or block office."] * 3
             + ["Fill the form at your bank branch."],
}


def fake_translate(hid, result):
    return {"summary": EN["summary"],
            "cards": [{"i": i, "member": c["member"], "benefit": EN["benefit"][i], "documents": EN["docs"][i],
                       "where_to_apply": EN["where"][i], "scheme_name": c["name_hi"]}
                      for i, c in enumerate(result["cards"])]}


def fake_extract(usage, **kw):
    p = {**intake.empty_profile(),
         "members": [intake._member(relation="self", age=40, gender="male", occupation="farmer")]}
    return {k: v for k, v in p.items() if k not in ("state", "assumptions")}


agent.run = fake_run
present._translate = fake_translate
intake.structured = fake_extract


@appmod.app.post("/stub/release")
def _release():
    release.set()
    return {"released": True}


@appmod.app.post("/stub/reset")
def _reset():
    release.clear()
    return {"reset": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(appmod.app, host="127.0.0.1", port=int(os.environ.get("PORT", "8001")), log_level="warning")
