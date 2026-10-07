"""Entry pointer for the Streamlit app.

Run the multipage app with:

    streamlit run app/main.py
"""

import streamlit as st

st.set_page_config(page_title="Renewable Energy Simulator", page_icon="⚡")
st.title("Renewable Energy Simulator")
st.write("The multipage app lives in `app/main.py`.")
st.code("streamlit run app/main.py", language="bash")
st.caption(
    "Version 2.1.0 is a screening model. It is not a PVsyst or WindPro equivalent, "
    "and its energy totals are not comparable to 2.0.0."
)
