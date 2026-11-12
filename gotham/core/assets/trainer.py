"""Bundled resumable trainer executed INSIDE the research sandbox.
Trains an SGD classifier epoch-by-epoch with checkpoints; `--resume` continues from the last checkpoint."""
import argparse, json, os, pickle, sys, time
import numpy as np
from sklearn.datasets import make_classification
from sklearn.linear_model import SGDClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score

ap = argparse.ArgumentParser()
ap.add_argument('--epochs', type=int, default=10)
ap.add_argument('--lr', type=float, default=0.01)
ap.add_argument('--seed', type=int, default=0)
ap.add_argument('--samples', type=int, default=2000)
ap.add_argument('--resume', action='store_true')
ap.add_argument('--stop-after', type=int, default=0, help='simulate interruption after N epochs (0=off)')
ap.add_argument('--csv', default='')
a = ap.parse_args()
os.makedirs('ckpt', exist_ok=True)
if a.csv:
    import pandas as pd
    df = pd.read_csv(a.csv)
    X, y = df.drop(columns=['label']).to_numpy(), df['label'].to_numpy()
else:
    X, y = make_classification(n_samples=a.samples, n_features=20, n_informative=8, random_state=a.seed)
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=a.seed)
classes = np.unique(y)
start, model = 0, SGDClassifier(loss='log_loss', learning_rate='constant', eta0=a.lr, random_state=a.seed)
ck = 'ckpt/last.pkl'
if a.resume and os.path.exists(ck):
    with open(ck, 'rb') as f:
        state = pickle.load(f)  # file produced by this trainer in this workspace
    model, start = state['model'], state['epoch']
    print(f'RESUMED from epoch {start}')
for ep in range(start, a.epochs):
    rng = np.random.RandomState(a.seed + ep)
    idx = rng.permutation(len(Xtr))
    model.partial_fit(Xtr[idx], ytr[idx], classes=classes)
    m = {'epoch': ep + 1, 'acc': float(accuracy_score(yte, model.predict(Xte))),
         'f1': float(f1_score(yte, model.predict(Xte))), 'ts': time.time()}
    with open('metrics.jsonl', 'a') as f:
        f.write(json.dumps(m) + '\n')
    with open(ck + '.tmp', 'wb') as f:
        pickle.dump({'model': model, 'epoch': ep + 1}, f)
    os.replace(ck + '.tmp', ck)
    print(json.dumps(m))
    if a.stop_after and ep + 1 >= a.stop_after and ep + 1 < a.epochs:
        print('SIMULATED_INTERRUPT'); sys.exit(75)
final = {'epochs_completed': a.epochs, 'final_acc': m['acc'], 'final_f1': m['f1'], 'hyperparameters': vars(a)}
json.dump(final, open('final.json', 'w'))
print('TRAINING_COMPLETE', json.dumps(final))
