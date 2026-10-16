"""Reproducible native cosine throughput microbenchmark, NOT retrieval quality."""
import argparse
import json
import statistics
import time

import numpy as np
from sceneseek.native import SimilarityIndex


parser = argparse.ArgumentParser()
parser.add_argument('--rows', type=int, default=100000)
parser.add_argument('--dimensions', type=int, default=512)
parser.add_argument('--repeats', type=int, default=5)
args = parser.parse_args()
index = SimilarityIndex()
assert index.backend == 'cpp', 'Build the C++ core first'
matrix = np.random.default_rng(23).standard_normal((args.rows,args.dimensions),dtype=np.float32)
query = matrix[42].copy()
index.top_k(query,matrix,10)
times = []
for _ in range(args.repeats):
    started = time.perf_counter()
    result = index.top_k(query,matrix,10)
    times.append((time.perf_counter()-started)*1000)
    assert result[0][0] == 42 and result[0][1] > .999
print(json.dumps({'backend':'cpp','rows':args.rows,'dimensions':args.dimensions,'matrix_mib':matrix.nbytes/1024**2,'repeats':args.repeats,'median_ms':round(statistics.median(times),2),'min_ms':round(min(times),2),'max_ms':round(max(times),2),'includes_embedding_and_io':False},indent=2))
