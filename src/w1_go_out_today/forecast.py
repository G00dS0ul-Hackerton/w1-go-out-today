import time
import os
import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error, roc_auc_score, brier_score_loss
from datetime import timedelta

from dotenv import load_dotenv
load_dotenv()

# Monkeypatch threadpoolctl to fix Windows paths with emojis breaking ctypes
import threadpoolctl
threadpoolctl.ThreadpoolController._find_libraries_on_windows = lambda self: None

from tabpfn import TabPFNClassifier, TabPFNRegressor

def prepare_data(df, n=12, is_training=True):
    df = df.copy()
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values('time').reset_index(drop=True)
        df.set_index('time', inplace=True)
    
    df['press_diff_3h'] = df['pressure_msl'] - df['pressure_msl'].shift(3)
    df['hum_diff_3h'] = df['relative_humidity_2m'] - df['relative_humidity_2m'].shift(3)
    df['rain_last_3h'] = df['precipitation'].rolling(3).sum()
    
    base_cols = [
        'temperature_2m', 'relative_humidity_2m', 'dew_point_2m', 
        'precipitation', 'cloud_cover', 'pressure_msl', 'wind_speed_10m',
        'press_diff_3h', 'hum_diff_3h', 'rain_last_3h'
    ]
    
    df_features = df[base_cols].dropna()
    
    dfs = []
    for h in range(1, n + 1):
        df_h = df_features.copy()
        df_h['hours_ahead'] = h
        
        target_time = df_h.index + timedelta(hours=h)
        df_h['target_hour'] = target_time.hour
        df_h['target_month'] = target_time.month
        
        if is_training:
            targets = df[['temperature_2m', 'precipitation']].reindex(target_time)
            targets.index = df_h.index
            df_h['temp_target'] = targets['temperature_2m']
            df_h['rain_target'] = (targets['precipitation'] >= 0.1).astype(int)
            df_h = df_h.dropna(subset=['temp_target', 'rain_target'])
        
        dfs.append(df_h)
        
    final_df = pd.concat(dfs).sort_index()
    return final_df

def get_splits(df_pairs, train_size=3000):
    max_time = df_pairs.index.max()
    test_start = max_time - timedelta(days=30)
    
    df_pre_test = df_pairs[df_pairs.index < test_start].copy()
    df_test = df_pairs[(df_pairs.index >= test_start) & (df_pairs.index.hour == 6)].copy()
    
    train_start = test_start - timedelta(days=365)
    df_train_pool = df_pre_test[df_pre_test.index >= train_start].copy()
    
    if len(df_train_pool) > train_size:
        df_train = df_train_pool.sample(n=train_size, random_state=42)
    else:
        df_train = df_train_pool
        
    return df_train, df_test, df_pre_test

def build_climatology(df_pre_test):
    clim_temp = df_pre_test.groupby(['target_month', 'target_hour'])['temp_target'].mean().reset_index()
    clim_rain = df_pre_test.groupby(['target_month', 'target_hour'])['rain_target'].mean().reset_index()
    
    clim = pd.merge(clim_temp, clim_rain, on=['target_month', 'target_hour'], suffixes=('', '_rain'))
    clim.rename(columns={'temp_target': 'clim_temp', 'rain_target': 'clim_rain_prob'}, inplace=True)
    return clim

def train_and_evaluate(df_train, df_test, df_pre_test, n_estimators=2, quiet=False):
    features = [
        'temperature_2m', 'relative_humidity_2m', 'dew_point_2m', 
        'precipitation', 'cloud_cover', 'pressure_msl', 'wind_speed_10m',
        'press_diff_3h', 'hum_diff_3h', 'rain_last_3h',
        'hours_ahead', 'target_hour', 'target_month'
    ]
    
    X_train = df_train[features]
    y_train_temp = df_train['temp_target']
    y_train_rain = df_train['rain_target']
    
    X_test = df_test[features]
    y_test_temp = df_test['temp_target']
    y_test_rain = df_test['rain_target']
    
    clim = build_climatology(df_pre_test)
    test_with_clim = pd.merge(df_test.reset_index(), clim, on=['target_month', 'target_hour'], how='left')
    
    base_mae_clim = mean_absolute_error(test_with_clim['temp_target'], test_with_clim['clim_temp'])
    base_roc_clim = roc_auc_score(test_with_clim['rain_target'], test_with_clim['clim_rain_prob'])
    base_brier_clim = brier_score_loss(test_with_clim['rain_target'], test_with_clim['clim_rain_prob'])
    
    pers_temp = test_with_clim['temperature_2m']
    pers_rain_prob = (test_with_clim['precipitation'] >= 0.1).astype(int)
    
    base_mae_pers = mean_absolute_error(test_with_clim['temp_target'], pers_temp)
    base_roc_pers = roc_auc_score(test_with_clim['rain_target'], pers_rain_prob)
    base_brier_pers = brier_score_loss(test_with_clim['rain_target'], pers_rain_prob)

    if not quiet:
        print(f"\n--- Baselines ---")
        print(f"Climatology: Temp MAE={base_mae_clim:.3f}, Rain ROC={base_roc_clim:.3f}, Rain Brier={base_brier_clim:.3f}")
        print(f"Persistence: Temp MAE={base_mae_pers:.3f}, Rain ROC={base_roc_pers:.3f}, Rain Brier={base_brier_pers:.3f}")
        
        print(f"\n--- TabPFN (n_estimators={n_estimators}) ---")
        
    t0 = time.time()
    clf = TabPFNClassifier(n_estimators=n_estimators)
    clf.fit(X_train, y_train_rain)
    reg = TabPFNRegressor(n_estimators=n_estimators)
    reg.fit(X_train, y_train_temp)
    fit_time = time.time() - t0
    
    t0 = time.time()
    rain_probs = clf.predict_proba(X_test)[:, 1] if len(clf.classes_) > 1 else np.zeros(len(X_test))
    temp_preds = reg.predict(X_test)
    pred_time = time.time() - t0
    
    roc = roc_auc_score(y_test_rain, rain_probs)
    brier = brier_score_loss(y_test_rain, rain_probs)
    mae = mean_absolute_error(y_test_temp, temp_preds)
    total_time = fit_time + pred_time
    
    if not quiet:
        print(f"Fit time: {fit_time:.2f}s | Predict time: {pred_time:.2f}s | Total: {total_time:.2f}s")
        print(f"TabPFN overall: Temp MAE={mae:.3f}, Rain ROC={roc:.3f}, Rain Brier={brier:.3f}")
        
        results = test_with_clim.copy()
        results['tabpfn_temp'] = temp_preds
        results['tabpfn_rain'] = rain_probs
        
        for h in sorted(results['hours_ahead'].unique()):
            sub = results[results['hours_ahead'] == h]
            if len(sub) > 0 and len(sub['rain_target'].unique()) > 1:
                h_mae = mean_absolute_error(sub['temp_target'], sub['tabpfn_temp'])
                h_roc = roc_auc_score(sub['rain_target'], sub['tabpfn_rain'])
                h_brier = brier_score_loss(sub['rain_target'], sub['tabpfn_rain'])
                print(f" +{h}h: MAE={h_mae:.3f}, ROC={h_roc:.3f}, Brier={h_brier:.3f}")

    return clf, reg, features, mae, roc, brier, total_time

def forecast(df, issue_time, n=12, clf=None, reg=None, features=None):
    df_pairs = prepare_data(df, n=n, is_training=False)
    
    if clf is None or reg is None:
        raise ValueError("Models not provided.")
        
    issue_data = df_pairs[df_pairs.index == pd.to_datetime(issue_time)].copy()
    if len(issue_data) == 0:
        raise ValueError(f"Issue time {issue_time} not found in prepared data.")
    
    issue_data = issue_data.sort_values('hours_ahead')
        
    X = issue_data[features]
    rain_probs = clf.predict_proba(X)[:, 1]
    temp_preds = reg.predict(X)
    
    res = []
    for i, h in enumerate(issue_data['hours_ahead']):
        target_time = pd.to_datetime(issue_time) + timedelta(hours=int(h))
        res.append({
            'time': target_time.strftime('%H:%M'),
            'hours_ahead': h,
            'temp_pred': f"{temp_preds[i]:.1f}°C",
            'rain_prob': f"{int(round(rain_probs[i]*100))}%"
        })
    return pd.DataFrame(res)

import sys
def run_forecast_evaluation():
    csv_path = "data/lagos_weather.csv"
    if not os.path.exists(csv_path):
        print(f"CSV not found at {csv_path}")
        return
        
    df = pd.read_csv(csv_path)
    df_pairs = prepare_data(df, n=12, is_training=True)
    
    if "--sample-size-check" in sys.argv:
        print("\n=== Sample Size Check (n_estimators=2) ===")
        print(f"{'Rows':>6} | {'Temp MAE':>8} | {'Rain AUC':>8} | {'Rain Brier':>10} | {'Total Time':>10}")
        print("-" * 55)
        for size in [1000, 3000, 5000]:
            df_train, df_test, df_pre_test = get_splits(df_pairs, train_size=size)
            _, _, _, mae, roc, brier, total_time = train_and_evaluate(df_train, df_test, df_pre_test, n_estimators=2, quiet=True)
            print(f"{size:>6} | {mae:>8.3f} | {roc:>8.3f} | {brier:>10.3f} | {total_time:>9.2f}s")
        return
    
    df_train, df_test, df_pre_test = get_splits(df_pairs, train_size=3000)
    
    print(f"Split Date: {df_test.index.min()} to {df_test.index.max()}")
    print(f"Train rows: {len(df_train)}, Test rows: {len(df_test)}")
    
    t_start = time.time()
    clf_def, reg_def, feats, _, _, _, _ = train_and_evaluate(df_train, df_test, df_pre_test, n_estimators=2)
    
    if "--compare" in sys.argv:
        print("\n=== Running n_estimators=10 Comparison ===")
        train_and_evaluate(df_train, df_test, df_pre_test, n_estimators=10)
        t_total = time.time() - t_start
        if t_total > 300:
            print("\nWARNING: Run took > 5 minutes. Consider using the TabPFN API client fallback.")
    
    # Live forecast from latest 06:00
    df['time'] = pd.to_datetime(df['time'])
    latest_06 = df[df['time'].dt.hour == 6]['time'].max()
    
    # Or accept from args
    for arg in sys.argv:
        if arg.startswith("--issue-time="):
            latest_06 = pd.to_datetime(arg.split("=")[1])
        
    print(f"\n--- Forecast for issue time ({latest_06}) ---")
    try:
        fcst = forecast(df, latest_06, n=12, clf=clf_def, reg=reg_def, features=feats)
        
        # Look up actuals
        has_actuals = False
        actual_temps = []
        actual_rains = []
        df_indexed = df.set_index('time')
        
        for h in fcst['hours_ahead']:
            target_time = latest_06 + timedelta(hours=int(h))
            if target_time in df_indexed.index:
                row = df_indexed.loc[target_time]
                if not pd.isna(row['temperature_2m']) and not pd.isna(row['precipitation']):
                    actual_temps.append(row['temperature_2m'])
                    actual_rains.append("Yes" if row['precipitation'] >= 0.1 else "No")
                    has_actuals = True
                    continue
            actual_temps.append(None)
            actual_rains.append(None)
            
        fcst['actual temp'] = [f"{t:.1f}°C" if t is not None else "-" for t in actual_temps]
        fcst['actually rained?'] = [r if r is not None else "-" for r in actual_rains]
        
        fcst = fcst.rename(columns={'temp_pred': 'forecast temp', 'rain_prob': 'rain chance'})
        
        cols_to_print = ['time', 'forecast temp', 'actual temp', 'rain chance', 'actually rained?']
        if not has_actuals:
            cols_to_print = ['time', 'forecast temp', 'rain chance']
            
        print(fcst[cols_to_print].to_string(index=False))
        
        if has_actuals:
            valid_idx = [i for i, t in enumerate(actual_temps) if t is not None]
            raw_temp_preds = [float(t.replace('°C', '')) for t in fcst['forecast temp']]
            raw_rain_probs = [int(p.replace('%', '')) for p in fcst['rain chance']]
            errs = [abs(raw_temp_preds[i] - actual_temps[i]) for i in valid_idx]
            avg_err = sum(errs) / len(errs) if errs else 0
            rainy_hits = sum(1 for i in valid_idx if actual_rains[i] == "Yes" and raw_rain_probs[i] > 50)
            rainy_total = sum(1 for i in valid_idx if actual_rains[i] == "Yes")
            print(f"\nSummary for {latest_06.date()}: Avg temp error {avg_err:.1f}°C. Rainy hours predicted (>50% chance): {rainy_hits}/{rainy_total}.")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Forecast failed: {e}")


if __name__ == "__main__":
    run_forecast_evaluation()
