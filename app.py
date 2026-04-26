st.markdown("---")
st.subheader("Графики по отелю")


def chart_to_number(value):
    if value is None or pd.isna(value):
        return None

    s = str(value).strip()
    s = s.replace("\xa0", " ")
    s = s.replace(" ", "")
    s = s.replace("RUR", "")
    s = s.replace("%", "")

    # вариант 4,114.34 — запятая как разделитель тысяч
    if "," in s and "." in s:
        s = s.replace(",", "")

    # вариант 4114,34 — запятая как десятичный разделитель
    elif "," in s and "." not in s:
        s = s.replace(",", ".")

    try:
        return float(s)
    except Exception:
        return None


if history.empty:
    st.write("Нет данных")
else:
    history_chart = history.copy()
    history_chart.columns = [str(c).strip() for c in history_chart.columns]

    required_columns = [
        "date",
        "hotel",
        "hotel_total_revenue_actual",
        "revpar_actual",
        "fb_total_revenue_actual",
        "service_hour_actual",
        "kitchen_hour_actual",
    ]

    missing = [c for c in required_columns if c not in history_chart.columns]

    if missing:
        st.error(f"В истории не хватает колонок: {missing}")
        st.write("Доступные колонки:", list(history_chart.columns))
    else:
        history_chart["_date"] = pd.to_datetime(
            history_chart["date"],
            errors="coerce",
            utc=True
        )

        history_chart = history_chart.dropna(subset=["_date"])

        metric_options = {
            "Hotel Total Revenue": "hotel_total_revenue_actual",
            "RevPAR": "revpar_actual",
            "F&B Total Revenue": "fb_total_revenue_actual",
            "Service / wtrs. hour": "service_hour_actual",
            "Kitchen / ktch. hour": "kitchen_hour_actual",
        }

        hotel_filter = st.selectbox(
            "Выбери отель",
            sorted(history_chart["hotel"].dropna().unique().tolist()),
            key="chart_hotel_filter_final"
        )

        selected_metric_name = st.selectbox(
            "Показатель",
            list(metric_options.keys()),
            index=0,
            key="chart_metric_filter_final"
        )

        chart_column = metric_options[selected_metric_name]

        filtered = history_chart[history_chart["hotel"] == hotel_filter].copy()

        filtered[chart_column] = filtered[chart_column].apply(chart_to_number)

        chart_df = filtered[["_date", chart_column]].dropna().copy()
        chart_df = chart_df.sort_values("_date")

        if chart_df.empty:
            st.warning(f"Нет числовых данных для графика: {selected_metric_name}")
            st.write(filtered[["date", "hotel", chart_column]].tail(20))
        else:
            chart_df = chart_df.set_index("_date")
            chart_df = chart_df.rename(columns={chart_column: selected_metric_name})

            st.markdown(f"**{selected_metric_name}**")
            st.line_chart(chart_df)
