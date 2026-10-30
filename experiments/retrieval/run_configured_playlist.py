"""Run the YAML-configured pretrained CLAP playlist experiment."""
import argparse, hashlib, json, sys
from pathlib import Path
import numpy as np, yaml
from experiments.retrieval.playlist_data import load_partial_examples, load_video_embeddings, merge_embeddings, load_reference_candidate_ids, candidate_matrix
from experiments.retrieval.configured_pipeline import aggregate, retrieve, seed_score, rank
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT/'spotify'/'src'))
from embeddings import get_embedder
import torch

device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def main():
 p=argparse.ArgumentParser(); p.add_argument('--config',type=Path,default=Path('experiments/retrieval/hp.yaml')); a=p.parse_args()
 cfg=yaml.safe_load(a.config.read_text()); paths=cfg['paths']; out,report=Path(paths['output']),Path(paths['report'])
 if out.exists() or report.exists(): p.error('output and report paths must be new')
 examples=load_partial_examples(Path(paths['inputs']),Path(paths['prompts']))
 vectors,origin=merge_embeddings([load_video_embeddings(Path(x)) for x in paths['embeddings']])
 ids,candidates=candidate_matrix(vectors,load_reference_candidate_ids(Path(paths['references'])))
 missing={e.example_id:[x for x in e.seed_video_ids if x not in vectors] for e in examples}; missing={k:v for k,v in missing.items() if v}
 if missing and cfg['coverage']['require_all_seed_embeddings']: raise ValueError(f'missing seed embeddings: {missing}')
 encoder=get_embedder(cfg['encoder']['name'],device=cfg['encoder'].get('device', device))
 if encoder.repo != cfg['encoder']['repository'] or candidates.shape[1] != cfg['encoder']['dimension']: raise ValueError('configured CLAP checkpoint/dimension is incompatible with cached embeddings')
 prompts=encoder.embed_text([e.prompt for e in examples])
 if prompts.shape[1] != candidates.shape[1]: raise ValueError('text/audio embedding dimension mismatch')
 predictions={}; details=[]
 for e,prompt in zip(examples,prompts):
  seeds=np.stack([vectors[x] for x in e.seed_video_ids]); seed=aggregate(seeds,prompt,cfg['seed_aggregation'])
  rows,text,_=retrieve(candidates,ids,prompt,seed,cfg['retrieval']); coherence=seed_score(candidates,seeds,cfg['ranking']['seed_similarity'],cfg['ranking']['seed_top_k'])
  if cfg['filtering']['exclude_seed_ids']: rows=[i for i in rows if ids[i] not in set(e.seed_video_ids)]
  final,scores=rank(rows,ids,candidates,text,coherence,{**cfg['ranking'],'top_k':cfg['output']['top_k'],'mmr_lambda':cfg['filtering']['mmr_lambda']})
  predictions[e.example_id]=[ids[i] for i in final]; details.append({'example_id':e.example_id,'seed_embedding_count':len(seeds),'recommendations':[{'video_id':ids[i],'score':float(scores[i])} for i in final]})
 out.parent.mkdir(parents=True,exist_ok=True); report.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(predictions,indent=2)+'\n')
 report.write_text(json.dumps({'config':cfg,'config_sha256':hashlib.sha256(a.config.read_bytes()).hexdigest(),'candidate_count':len(ids),'embedding_sources':paths['embeddings'],'missing_seed_embeddings':missing,'examples':details},indent=2)+'\n')
if __name__=='__main__': main()
