"""Config-driven, inference-only retrieval and ranking primitives."""
import numpy as np
from retrieval.catalog import normalized_vectors

def order(scores, ids, k):
    return sorted(range(len(ids)), key=lambda i: (-float(scores[i]), ids[i]))[:k]

def aggregate(seed_vectors, prompt, cfg):
    vectors = normalized_vectors(seed_vectors)
    method = cfg['method']
    if method == 'mean': row = vectors.mean(0)
    elif method == 'top_k_mean':
        take = order(vectors @ prompt, [str(i) for i in range(len(vectors))], min(cfg['top_k'], len(vectors)))
        row = vectors[take].mean(0)
    elif method == 'prompt_weighted_mean':
        raw = (vectors @ prompt) / cfg['temperature']; weights = np.exp(raw - raw.max()); row = (vectors * (weights / weights.sum())[:, None]).sum(0)
    else: raise ValueError(f"unknown seed aggregation: {method}")
    return normalized_vectors(row.reshape(1, -1))[0]

def seed_score(candidates, seeds, method, top_k):
    values = candidates @ seeds.T
    if method == 'mean': return values.mean(1)
    if method == 'max': return values.max(1)
    if method == 'top_k_mean': return np.sort(values, axis=1)[:, -min(top_k, values.shape[1]):].mean(1)
    raise ValueError(f"unknown seed similarity: {method}")

def retrieve(candidates, ids, prompt, seed, cfg):
    method, k = cfg['method'], cfg['candidate_k']
    text, playlist = candidates @ prompt, candidates @ seed
    if method == 'text_only': return order(text, ids, k), text, playlist
    if method == 'seed_only': return order(playlist, ids, k), text, playlist
    if method == 'early_fusion':
        query = normalized_vectors((cfg['prompt_weight'] * prompt + (1-cfg['prompt_weight']) * seed).reshape(1,-1))[0]
        return order(candidates @ query, ids, k), text, playlist
    if method == 'multi_query': return sorted(set(order(text, ids, k)) | set(order(playlist, ids, k))), text, playlist
    raise ValueError(f"unknown retrieval method: {method}")

def rank(rows, ids, candidates, prompt_scores, seed_scores, cfg):
    method = cfg['method']
    if method == 'cosine': scores = prompt_scores
    elif method == 'weighted_score': scores = cfg['prompt_weight'] * prompt_scores + (1-cfg['prompt_weight']) * seed_scores
    elif method == 'rrf':
        pr = {i:r for r,i in enumerate(order(prompt_scores, ids, len(ids)), 1)}; sr = {i:r for r,i in enumerate(order(seed_scores, ids, len(ids)), 1)}
        scores = np.array([1/(cfg['rrf_k']+pr[i])+1/(cfg['rrf_k']+sr[i]) for i in range(len(ids))])
    else: raise ValueError(f"unknown ranking method: {method}")
    # Greedy MMR over final candidates; lambda=1 preserves the base rank.
    selected=[]
    while rows and len(selected) < cfg['top_k']:
        best=max(rows, key=lambda i: (cfg['mmr_lambda']*scores[i] - (1-cfg['mmr_lambda'])*max([float(candidates[i]@candidates[j]) for j in selected], default=0), ids[i]))
        rows.remove(best); selected.append(best)
    return selected, scores
