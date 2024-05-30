import os
import pickle
import subprocess

import networkx as nx
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


def draw_graph(g, layout):
    agraph = nx.nx_agraph.to_agraph(g)
    svg = agraph.draw(prog=layout, format='svg')
    return svg


def load_graph():
    with open("graph.pkl", "rb") as f:
        return pickle.load(f)


G = load_graph()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate_svg', methods=['POST'])
def generate_svg():
    data = request.json
    package_name = data.get('package_name')
    depth = data.get('depth')
    undirected = data.get('undirected')
    layout = data.get('layout')

    subgraph = nx.ego_graph(G, package_name, depth, undirected=undirected)

    svg_content = draw_graph(subgraph, layout)

    return svg_content


if __name__ == '__main__':
    app.run(debug=True)
