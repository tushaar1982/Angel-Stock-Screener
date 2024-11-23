import dash
from dash import dcc, html, Input, Output, dash_table
import pandas as pd
import requests
from dash.dependencies import Input, Output
from datetime import datetime

# Initialize the Dash app
app = dash.Dash(__name__)
app.title = "Stock Signals Dashboard"

# Layout of the app
app.layout = html.Div(
    children=[
        html.H1("Stock Signals Dashboard", style={"text-align": "center"}),
        dcc.Interval(
            id="interval-component",
            interval=30* 1000,  # 1 minute in milliseconds
            n_intervals=0,
        ),
        html.Div(
            id="last-update",
            style={"text-align": "center", "margin-bottom": "20px"}
        ),
        dash_table.DataTable(
            id="signals-table",
            columns=[
                {"name": "Symbol", "id": "symbol"},
                {"name": "Token", "id": "token"},
                {"name": "Price", "id": "price"},
                {"name": "Signal", "id": "signal"},
            ],
            style_data_conditional=[
                {
                    "if": {"filter_query": "{signal} eq 'BUY'", "column_id": "signal"},
                    "backgroundColor": "green",
                    "color": "white",
                },
                {
                    "if": {"filter_query": "{signal} eq 'SELL'", "column_id": "signal"},
                    "backgroundColor": "red",
                    "color": "white",
                },
            ],
            style_table={"width": "80%", "margin": "auto"},
            style_header={
                "backgroundColor": "lightgrey",
                "fontWeight": "bold",
                "textAlign": "center",
            },
            style_cell={
                "textAlign": "center",
                "padding": "10px",
                "fontSize": "16px",
            },
        ),
    ]
)

# Backend API URL
API_URL = "http://0.0.0.0:8000/signals"

# Callback to fetch and display data
@app.callback(
    [Output("signals-table", "data"), Output("last-update", "children")],
    [Input("interval-component", "n_intervals")],
)
def update_table(n_intervals):
    try:
        # Fetch data from the FastAPI backend
        response = requests.get(API_URL)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data)
                update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return df.to_dict("records"), f"Last Update: {update_time}"
            else:
                return [], "No signals generated. Last Update: {}".format(
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
        else:
            return [], f"Error fetching data: {response.status_code}"
    except Exception as e:
        return [], f"Error: {str(e)}"


# Run the app
if __name__ == "__main__":
    app.run_server(debug=True)
