import pandas as pd
import streamlit as st
from datetime import timedelta, datetime
import re
from lib.dataprep.clean import clean_future_df
from lib.utils.mapping import convert_into_nb_of_days, convert_into_nb_of_seconds


def get_train_val_sets(df: pd.DataFrame, dates: dict, config: dict) -> dict:
    datasets = dict()
    train = df.query(f'ds >= "{dates["train_start_date"]}" & ds <= "{dates["train_end_date"]}"').copy()
    val = df.query(f'ds >= "{dates["val_start_date"]}" & ds <= "{dates["val_end_date"]}"').copy()
    datasets['train'], datasets['val'], datasets['full'] = train, val, df.copy()
    print_train_val_dates(val, train)
    raise_error_train_val_dates(val, train, config)
    return datasets


def print_train_val_dates(val: pd.DataFrame, train: pd.DataFrame):
    st.success(f"""Train: [ {train.ds.min().strftime('%Y/%m/%d')} - 
                           {train.ds.max().strftime('%Y/%m/%d')} ]
                    Valid: [ {val.ds.min().strftime('%Y/%m/%d')} - 
                           {val.ds.max().strftime('%Y/%m/%d')} ]
                        ({round((len(val) / float(len(train) + len(val)) * 100))}% of data used for validation)""")


def raise_error_train_val_dates(val: pd.DataFrame, train: pd.DataFrame, config: dict):
    threshold_train = config['validity']['min_data_points_train']
    threshold_val = config['validity']['min_data_points_val']
    if len(val) <= threshold_val:
        st.error(f"There are less than {threshold_val + 1} data points in validation set ({len(val)}), "
                 f"please expand validation period or change the dataset frequency.")
        st.stop()
    if len(train) <= threshold_train:
        st.error(f"There are less than {threshold_train + 1} data points in training set ({len(train)}), "
                 f"please expand training period or change the dataset frequency.")
        st.stop()


def get_train_set(df: pd.DataFrame, dates: dict) -> dict:
    datasets = dict()
    train = df.query(f'ds >= "{dates["train_start_date"]}" & ds <= "{dates["train_end_date"]}"').copy()
    datasets['train'] = train
    datasets['full'] = df.copy()
    return datasets


def make_eval_df(datasets: dict) -> dict:
    eval = pd.concat([datasets['train'], datasets['val']], axis=0)
    eval = eval.drop('y', axis=1)
    datasets['eval'] = eval
    return datasets


def make_future_df(dates: dict, datasets: dict, cleaning: dict, include_history: bool = True) -> dict:
    # TODO: Inclure les valeurs futures de régresseurs ? Pour l'instant, use_regressors = False pour le forecast
    if include_history:
        start_date = datasets['full'].ds.min()
    else:
        start_date = dates['forecast_start_date']
    future = pd.date_range(start=start_date, end=dates['forecast_end_date'], freq=dates['forecast_freq'])
    future = pd.DataFrame(future, columns=['ds'])
    future = clean_future_df(future, cleaning)
    datasets['future'] = future
    return datasets


def get_train_end_date_default_value(df: pd.DataFrame, dates: dict, resampling: dict, config: dict, use_cv: bool):
    if use_cv:
        default_end = df.ds.max()
    else:
        total_nb_days = (df.ds.max().date() - dates['train_start_date']).days
        freq = resampling['freq'][-1]
        default_horizon = convert_into_nb_of_days(freq, config['horizon'][freq])
        default_end = df.ds.max() - timedelta(days=min(default_horizon, total_nb_days - 1))
    return default_end


def get_cv_cutoffs(dates: dict, freq: str) -> list:
    horizon, end, n_folds = dates['folds_horizon'], dates['train_end_date'], dates['n_folds']
    if freq in ['s', 'H']:
        end = datetime.combine(end, datetime.min.time())
        cutoffs = [pd.to_datetime(end - timedelta(seconds=(i + 1) * convert_into_nb_of_seconds(freq, horizon)))
                   for i in range(n_folds)]
    else:
        cutoffs = [pd.to_datetime(end - timedelta(days=(i + 1) * convert_into_nb_of_days(freq, horizon)))
                   for i in range(n_folds)]
    return cutoffs


def get_max_possible_cv_horizon(dates: dict, resampling: dict) -> int:
    freq = resampling['freq'][-1]
    if freq in ['s', 'H']:
        nb_seconds_training = (dates['train_end_date'] - dates['train_start_date']).days * (24 * 60 * 60)
        max_horizon = (nb_seconds_training // convert_into_nb_of_seconds(freq, 1)) // dates['n_folds']
    else:
        nb_days_training = (dates['train_end_date'] - dates['train_start_date']).days
        max_horizon = (nb_days_training // convert_into_nb_of_days(freq, 1)) // dates['n_folds']
    return max_horizon


def print_cv_folds_dates(dates: dict, freq: str):
    horizon, cutoffs_text = dates['folds_horizon'], []
    for i, cutoff in enumerate(dates['cutoffs']):
        cutoffs_text.append(f"""Fold {i + 1}:           """)
        if freq in ['s', 'H']:
            cutoffs_text.append(f"""Train: [ {dates['train_start_date'].strftime('%Y/%m/%d %H:%M:%S')} - """
                                f"""{cutoff.strftime('%Y/%m/%d %H:%M:%S')} ]""")
            cutoffs_text.append(f"""Valid: ] {cutoff.strftime('%Y/%m/%d %H:%M:%S')} - """
                                f"""{(cutoff + timedelta(seconds=convert_into_nb_of_seconds(freq, horizon)))
                                .strftime('%Y/%m/%d %H:%M:%S')} ]""")
        else:
            cutoffs_text.append(f"""Train: [ {dates['train_start_date'].strftime('%Y/%m/%d')} - """
                                f"""{cutoff.strftime('%Y/%m/%d')} ]""")
            cutoffs_text.append(f"""Valid: ] {cutoff.strftime('%Y/%m/%d')} - """
                                f"""{(cutoff + timedelta(days=convert_into_nb_of_days(freq, horizon)))
                                .strftime('%Y/%m/%d')} ]""")
        cutoffs_text.append("")
    st.success('\n'.join(cutoffs_text))


def raise_error_cv_dates(dates: dict, resampling: dict, config: dict):
    threshold_train = config['validity']['min_data_points_train']
    threshold_val = config['validity']['min_data_points_val']
    freq = resampling['freq']
    regex = re.findall(r'\d+', resampling['freq'])
    freq_int = int(regex[0]) if len(regex) > 0 else 1
    n_data_points_val = dates['folds_horizon'] // freq_int
    n_data_points_train = len(pd.date_range(start=dates['train_start_date'], end=min(dates['cutoffs']), freq=freq))
    if n_data_points_val <= threshold_val:
        st.error(f"Some folds' valid sets have less than {threshold_val + 1} data points ({n_data_points_val}), "
                 f"please increase folds' horizon or change the dataset frequency or expand CV period.")
        st.stop()
    elif n_data_points_train <= threshold_train:
        st.error(f"Some folds' train sets have less than {threshold_train + 1} data points ({n_data_points_train}), "
                 f"please increase folds' horizon or change the dataset frequency or expand CV period.")
        st.stop()


def print_forecast_dates(dates: dict, resampling: dict):
    if resampling['freq'][-1] in ['s', 'H']:
        st.success(f"""Forecast: {dates['forecast_start_date'].strftime('%Y/%m/%d %H:%M:%S')} - 
                                 {dates['forecast_end_date'].strftime('%Y/%m/%d %H:%M:%S')}""")
    else:
        st.success(f"""Forecast: {dates['forecast_start_date'].strftime('%Y/%m/%d')} - 
                                 {dates['forecast_end_date'].strftime('%Y/%m/%d')}""")