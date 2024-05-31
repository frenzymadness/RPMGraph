FROM quay.io/fedora/fedora:rawhide

RUN dnf install -y python3-dnf python3-networkx python3-tqdm

COPY lib.py generate_graph_file.py ./

CMD python3 ./generate_graph_file.py
