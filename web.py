import gzip
import json
import pickle
import subprocess
from pathlib import Path

import networkx as nx
from flask import Flask, render_template, request

app = Flask(__name__)


def graph_to_JSON(g):
    colors = nx.get_edge_attributes(g, "color")
    d = {
        "nodes": [{"data": {"id": str(node), "label": str(node)}} for node in g.nodes],
        "edges": [
            {
                "data": {
                    "source": str(edge[0]),
                    "target": str(edge[1]),
                    "color": colors[edge],
                }
            }
            for edge in g.edges
        ],
    }

    return json.dumps(d)


def draw_graph(g, layout):
    agraph = nx.nx_agraph.to_agraph(g)
    svg = agraph.draw(prog=layout, format="svg")
    return svg


def load_graph():
    with gzip.open(Path(__file__).parent / "graph.pkl.gz", "rb") as f:
        return pickle.load(f)


G = load_graph()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate_graph", methods=["POST"])
def generate_graph():
    data = request.json
    package_name = data.get("package_name")
    depth = data.get("depth")
    undirected = data.get("undirected")
    layout = data.get("layout")

    subgraph = nx.ego_graph(G, package_name, depth, undirected=undirected)

    graph_json = graph_to_JSON(subgraph)

    return graph_json


if __name__ == "__main__":
    app.run(debug=True)
