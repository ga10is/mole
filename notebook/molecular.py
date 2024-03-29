# -*- coding: utf-8 -*-
"""molecular.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1EiEJYOD9gt2PmpDLcAtoMUPji-jY5Ts9
"""

from google.colab import drive
drive.mount('/gdrive')

# %cd "/gdrive/My Drive"

# %matplotlib inline
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from sklearn.base import clone
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.preprocessing import LabelEncoder
import lightgbm as lgb
import math

from tqdm import tqdm
import joblib
import gc

"""## config"""

INPUT = './analysis/mole/data/raw/'
TRAIN_PATH = INPUT + 'train.csv'
TEST_PATH = INPUT + 'test.csv'
PREPROCESS = './analysis/mole/data/preprocess/'

MID_MODEL_PATH = PREPROCESS + 'middle_model.pkl'
MODEL_PATH = PREPROCESS + 'model.pkl'
ENCODER_PATH = PREPROCESS + 'le.pkl'

USE_PREPROCESS_DATA = False
TARGET = 'scalar_coupling_constant'
MERGE_KEY = ['molecule_name', 'atom_index_0', 'atom_index_1']
CONTR_COLS = ['fc', 'sd', 'pso', 'dso']
N_FOLDS = 3

atom_weight = {'H': 1.008, 'C': 12.01, 'N': 14.01, 'O':16.00}

"""## logging"""

import logging
import logging.handlers


def create_logger(log_file_name):
    logger_ = logging.getLogger('main')
    logger_.setLevel(logging.DEBUG)
    fh = logging.handlers.RotatingFileHandler(
        log_file_name, maxBytes=100000, backupCount=8)
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(levelname)s]%(asctime)s:%(name)s:%(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    # add the handlers to the logger
    logger_.addHandler(fh)
    logger_.addHandler(ch)


def get_logger():
    return logging.getLogger('main')

create_logger('mole.log')

"""## util"""

def onehot(_df):
    cat_names = [name for name, col in _df.iteritems() if col.dtype == 'O']
    df_cat = pd.get_dummies(_df[cat_names])
    _df = pd.concat([_df, df_cat], axis=1).drop(cat_names, axis=1)
    return _df

def label_encode(df):
    cat_names = [name for name, col in df.iteritems() if col.dtype == 'O']    
    for cat_name in cat_names:
        print(cat_name)
        le = LabelEncoder()
        le.fit(df[cat_name].values)
        df[cat_name] = le.transform(df[cat_name].values)
    return df

class Encoder:
    def __init__(self):        
        self.encoders = {}
    
    def fit(self, df, cat_names):
        for cat_name in cat_names:
            le = LabelEncoder()
            le.fit(df[cat_name].values)
            self.encoders[cat_name] = le        
    
    def transform(self, df):
        for cat_name in self.encoders.keys():            
            df[cat_name] = self.encoders[cat_name].transform(df[cat_name].values)
            
        return df


def reduce_mem_usage(df, verbose=True):
    numerics = ['int16', 'int32', 'int64', 'float16', 'float32', 'float64']
    start_mem = df.memory_usage().sum() / 1024**2    
    for col in df.columns:
        col_type = df[col].dtypes
        if col_type in numerics:
            c_min = df[col].min()
            c_max = df[col].max()
            if str(col_type)[:3] == 'int':
                if c_min > np.iinfo(np.int8).min and c_max < np.iinfo(np.int8).max:
                    df[col] = df[col].astype(np.int8)
                elif c_min > np.iinfo(np.int16).min and c_max < np.iinfo(np.int16).max:
                    df[col] = df[col].astype(np.int16)
                elif c_min > np.iinfo(np.int32).min and c_max < np.iinfo(np.int32).max:
                    df[col] = df[col].astype(np.int32)
                elif c_min > np.iinfo(np.int64).min and c_max < np.iinfo(np.int64).max:
                    df[col] = df[col].astype(np.int64)  
            else:
                if c_min > np.finfo(np.float16).min and c_max < np.finfo(np.float16).max:
                    df[col] = df[col].astype(np.float16)
                elif c_min > np.finfo(np.float32).min and c_max < np.finfo(np.float32).max:
                    df[col] = df[col].astype(np.float32)
                else:
                    df[col] = df[col].astype(np.float64)    
    end_mem = df.memory_usage().sum() / 1024**2
    if verbose: 
        print('Mem. usage decreased to {:5.2f} Mb ({:.1f}% reduction)'.format(end_mem, 100 * (start_mem - end_mem) / start_mem))
    
    return df

def reduce_mem_usage_v2(df, verbose=True):
    numerics = ['int16', 'int32', 'int64', 'float16', 'float32', 'float64']
    start_mem = df.memory_usage().sum() / 1024**2
    for col in df.columns:
        col_type = df[col].dtypes
        if col_type in numerics:
            c_min = df[col].min()
            c_max = df[col].max()
            if str(col_type)[:3] == 'int':
                if c_min > np.iinfo(np.int8).min and c_max < np.iinfo(np.int8).max:
                    df[col] = df[col].astype(np.int8)
                elif c_min > np.iinfo(np.int16).min and c_max < np.iinfo(np.int16).max:
                    df[col] = df[col].astype(np.int16)
                elif c_min > np.iinfo(np.int32).min and c_max < np.iinfo(np.int32).max:
                    df[col] = df[col].astype(np.int32)
                elif c_min > np.iinfo(np.int64).min and c_max < np.iinfo(np.int64).max:
                    df[col] = df[col].astype(np.int64)
            else:
                c_prec = df[col].apply(lambda x: np.finfo(x).precision).max()
                if c_min > np.finfo(np.float16).min and c_max < np.finfo(np.float16).max and c_prec == np.finfo(np.float16).precision:
                    df[col] = df[col].astype(np.float16)
                elif c_min > np.finfo(np.float32).min and c_max < np.finfo(np.float32).max and c_prec == np.finfo(np.float32).precision:
                    df[col] = df[col].astype(np.float32)
                else:
                    df[col] = df[col].astype(np.float64)
    end_mem = df.memory_usage().sum() / 1024**2
    if verbose: print('Mem. usage decreased to {:5.2f} Mb ({:.1f}% reduction)'.format(end_mem, 100 * (start_mem - end_mem) / start_mem))
    return df

"""## Preprocess"""

def map_atom_info(df, strct, atom_idx):
    df = pd.merge(df, strct, how = 'left',
                  left_on  = ['molecule_name', f'atom_index_{atom_idx}'],
                  right_on = ['molecule_name',  'atom_index'])
    
    df = df.drop('atom_index', axis=1)
    df = df.rename(columns={'atom': f'atom_{atom_idx}',
                            'x': f'x_{atom_idx}',
                            'y': f'y_{atom_idx}',
                            'z': f'z_{atom_idx}'})
    return df

def calc_dist(df):
    p_0 = df[['x_0', 'y_0', 'z_0']].values
    p_1 = df[['x_1', 'y_1', 'z_1']].values

    df['dist'] = np.linalg.norm(p_0 - p_1, axis=1)
    df['dist_x'] = (df['x_0'] - df['x_1']) ** 2
    df['dist_y'] = (df['y_0'] - df['y_1']) ** 2
    df['dist_z'] = (df['z_0'] - df['z_1']) ** 2

    return df

def divide_type(df):    
    df['type_0'] = df['type'].apply(lambda x: x[0])
    df['type_1'] = df['type'].apply(lambda x: x[1:])
    return df

def feature_engineering(df):
    print("Starting Feature Engineering...")
    g = df.groupby('molecule_name')
    g1 = df.groupby(['molecule_name', 'atom_index_0'])
    g2 = df.groupby(['molecule_name', 'atom_index_1'])
    g3 = df.groupby(['molecule_name', 'atom_1'])
    g4 = df.groupby(['molecule_name', 'type_0'])
    g5 = df.groupby(['molecule_name', 'type'])
    
    df['type_0'] = df['type'].apply(lambda x: x[0])
    df['molecule_couples'] = g['id'].transform('count')
    df['molecule_dist_mean'] = g['dist'].transform('mean')
    df['molecule_dist_min'] = g['dist'].transform('min')
    df['molecule_dist_max'] = g['dist'].transform('max')
    df['atom_0_couples_count'] = g1['id'].transform('count')
    df['atom_1_couples_count'] = g2['id'].transform('count')
    df[f'molecule_atom_index_0_x_1_std'] = g1['x_1'].transform('std')
    df[f'molecule_atom_index_0_y_1_mean'] = g1['y_1'].transform('mean')
    df[f'molecule_atom_index_0_y_1_mean_diff'] = df[f'molecule_atom_index_0_y_1_mean'] - df['y_1']
    df[f'molecule_atom_index_0_y_1_mean_div'] = df[f'molecule_atom_index_0_y_1_mean'] / df['y_1']
    df[f'molecule_atom_index_0_y_1_max'] = g1['y_1'].transform('max')
    df[f'molecule_atom_index_0_y_1_max_diff'] = df[f'molecule_atom_index_0_y_1_max'] - df['y_1']
    df[f'molecule_atom_index_0_y_1_std'] = g1['y_1'].transform('std')
    df[f'molecule_atom_index_0_z_1_std'] = g1['z_1'].transform('std')
    df[f'molecule_atom_index_0_dist_mean'] = g1['dist'].transform('mean')
    df[f'molecule_atom_index_0_dist_mean_diff'] = df[f'molecule_atom_index_0_dist_mean'] - df['dist']
    df[f'molecule_atom_index_0_dist_mean_div'] = df[f'molecule_atom_index_0_dist_mean'] / df['dist']
    df[f'molecule_atom_index_0_dist_max'] = g1['dist'].transform('max')
    df[f'molecule_atom_index_0_dist_max_diff'] = df[f'molecule_atom_index_0_dist_max'] - df['dist']
    df[f'molecule_atom_index_0_dist_max_div'] = df[f'molecule_atom_index_0_dist_max'] / df['dist']
    df[f'molecule_atom_index_0_dist_min'] = g1['dist'].transform('min')
    df[f'molecule_atom_index_0_dist_min_diff'] = df[f'molecule_atom_index_0_dist_min'] - df['dist']
    df[f'molecule_atom_index_0_dist_min_div'] = df[f'molecule_atom_index_0_dist_min'] / df['dist']
    df[f'molecule_atom_index_0_dist_std'] = g1['dist'].transform('std')
    df[f'molecule_atom_index_0_dist_std_diff'] = df[f'molecule_atom_index_0_dist_std'] - df['dist']
    df[f'molecule_atom_index_0_dist_std_div'] = df[f'molecule_atom_index_0_dist_std'] / df['dist']
    df[f'molecule_atom_index_1_dist_mean'] = g2['dist'].transform('mean')
    df[f'molecule_atom_index_1_dist_mean_diff'] = df[f'molecule_atom_index_1_dist_mean'] - df['dist']
    df[f'molecule_atom_index_1_dist_mean_div'] = df[f'molecule_atom_index_1_dist_mean'] / df['dist']
    df[f'molecule_atom_index_1_dist_max'] = g2['dist'].transform('max')
    df[f'molecule_atom_index_1_dist_max_diff'] = df[f'molecule_atom_index_1_dist_max'] - df['dist']
    df[f'molecule_atom_index_1_dist_max_div'] = df[f'molecule_atom_index_1_dist_max'] / df['dist']
    df[f'molecule_atom_index_1_dist_min'] = g2['dist'].transform('min')
    df[f'molecule_atom_index_1_dist_min_diff'] = df[f'molecule_atom_index_1_dist_min'] - df['dist']
    df[f'molecule_atom_index_1_dist_min_div'] = df[f'molecule_atom_index_1_dist_min'] / df['dist']
    df[f'molecule_atom_index_1_dist_std'] = g2['dist'].transform('std')
    df[f'molecule_atom_index_1_dist_std_diff'] = df[f'molecule_atom_index_1_dist_std'] - df['dist']
    df[f'molecule_atom_index_1_dist_std_div'] = df[f'molecule_atom_index_1_dist_std'] / df['dist']
    df[f'molecule_atom_1_dist_mean'] = g3['dist'].transform('mean')
    df[f'molecule_atom_1_dist_min'] = g3['dist'].transform('min')
    df[f'molecule_atom_1_dist_min_diff'] = df[f'molecule_atom_1_dist_min'] - df['dist']
    df[f'molecule_atom_1_dist_min_div'] = df[f'molecule_atom_1_dist_min'] / df['dist']
    df[f'molecule_atom_1_dist_std'] = g3['dist'].transform('std')
    df[f'molecule_atom_1_dist_std_diff'] = df[f'molecule_atom_1_dist_std'] - df['dist']
    df[f'molecule_type_0_dist_std'] = g4['dist'].transform('std')
    df[f'molecule_type_0_dist_std_diff'] = df[f'molecule_type_0_dist_std'] - df['dist']
    df[f'molecule_type_dist_mean'] = g5['dist'].transform('mean')
    df[f'molecule_type_dist_mean_diff'] = df[f'molecule_type_dist_mean'] - df['dist']
    df[f'molecule_type_dist_mean_div'] = df[f'molecule_type_dist_mean'] / df['dist']
    df[f'molecule_type_dist_max'] = g5['dist'].transform('max')
    df[f'molecule_type_dist_min'] = g5['dist'].transform('min')
    df[f'molecule_type_dist_std'] = g5['dist'].transform('std')
    df[f'molecule_type_dist_std_diff'] = df[f'molecule_type_dist_std'] - df['dist']

    # TODO: back
    # df = reduce_mem_usage(df)
    
    return df

def add_1j(df):
    get_logger().info('load df_1j')
    
    df_1j = joblib.load(PREPROCESS + 'df_1j.pkl')
    
    df = df.merge(df_1j, on=['molecule_name', 'atom_index_0', 'atom_index_1'], how='left') 
    
    return df


def add_2j_center_atom(df):    
    get_logger().info('load df_2jsim')
    
    df_2j = joblib.load(PREPROCESS + 'df_2jsim.pkl')  
    
    # atom weight
    df_2j['2j_atom_center_weight'] = df_2j['2j_atom_center'].replace(atom_weight)
    
    # sum of norm
    df_2j['2j_sum_norm_vec'] = df_2j['2j_norm_vec_02'] + df_2j['2j_norm_vec_12']
    
    df = df.merge(df_2j, on=['molecule_name', 'atom_index_0', 'atom_index_1'], how='left')    
    
    # replace missing vlaue to 'nan' for LabelEncoder
    df.loc[df['2j_atom_center'].isnull(), '2j_atom_center'] = 'nan'
    
    return df

def str_sort(s):
    """
    Parameters
    ----------
    x: str   
    """
    # print(s)
    if not isinstance(s, str):
        return s
    elif s[0] > s[1]:
        return s[1] + s[0]
    else:
        return s

def add_3j_center_atom(df):    
    get_logger().info('load df_3jsim')
    
    df_3j = joblib.load(PREPROCESS + 'df_3jsim.pkl')
    
    # atom weight
    s_atom_w0 = df_3j['3j_atom_center_0'].replace(atom_weight)
    s_atom_w1 = df_3j['3j_atom_center_1'].replace(atom_weight)
    df_3j['3j_atom_center_weight'] = s_atom_w0 + s_atom_w1

    # concatenate atom string 'C' + 'C' - > 'CC'
    tmp = df_3j['3j_atom_center_0'] + df_3j['3j_atom_center_1']
    df_3j['3j_atom_center'] = tmp.transform(str_sort)    
    df_3j.drop(['3j_atom_center_0', '3j_atom_center_1'], axis=1, inplace=True)
    
    # sum norm_vec
    df_3j['3j_sum_norm_vec'] = df_3j['3j_norm_vec_02'] + df_3j['3j_norm_vec_13'] + df_3j['3j_norm_vec_23']
    
    df = df.merge(df_3j, on=['molecule_name', 'atom_index_0', 'atom_index_1'], how='left')    
    
    # replace missing vlaue to 'nan' for LabelEncoder
    df.loc[df['3j_atom_center'].isnull(), '3j_atom_center'] = 'nan'    
    
    return df

def drop_col(df_org):
    df = df_org.copy()
    to_drop = ['id', 'molecule_name', 'atom_index_0', 'atom_index_1',
               'x_0', 'y_0', 'z_0', 'x_1', 'y_1', 'z_1', # 'dist_x', 'dist_y', 'dist_z',
               'atom_0', 'atom_1'
              ]
    df = df.drop(to_drop, axis=1)
    
    return df

def group_mean_log_mae(y_true, y_pred, types, floor=1e-9):
    """
    Fast metric computation for this competition: https://www.kaggle.com/c/champs-scalar-coupling
    Code is from this kernel: https://www.kaggle.com/uberkinder/efficient-metric
    """
    maes = (y_true-y_pred).abs().groupby(types).mean()    
    return np.log(maes.map(lambda x: max(x, floor))).mean()

def oof_train(X_org, y_org, _types):
# def oof_train(_X, _y, _types):
    """
    Parameters
    ----------
    _X: pd.DataFrame, shape [n_samples, n_features]
    _y: array-like object, shape [n_samples]
    _types: array-like object, shsape [n_samples]
        array of `type` (e.g. 2JHC, 1JHC, 3JHH, etc.)
    """
    # TODO: divide data to training and validation about molecular
    
    models = []
    # TODO: back
    _X = X_org.copy().reset_index(drop=True)
    _y = y_org.copy().reset_index(drop=True)
    df_scores = pd.DataFrame(columns=['valid_score'])
    df_pred = pd.DataFrame(index=_X.index).reset_index(drop=True)

    fold = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=1)
    for n_fold, (train_idx, valid_idx) in enumerate(fold.split(_X, _types)):
        # prepare data
        X_train, y_train = _X.iloc[train_idx], _y.iloc[train_idx]
        X_valid, y_valid = _X.iloc[valid_idx], _y.iloc[valid_idx]
        print('mean of target. train:{}, valid:{}'.format(y_train.mean(), y_valid.mean()))

        # generate model
        model = gen_model(_X)
        
        # train
        model.fit(X_train, y_train, eval_metric='mae',
                  eval_set=[(X_train, y_train), (X_valid, y_valid)],
                  verbose=100,
                  early_stopping_rounds=100
                  )
        
        # validate
        y_pred = model.predict(X_valid, num_iteration=model.best_iteration_)
        
        types_valid = _types.iloc[valid_idx]
        valid_score = group_mean_log_mae(y_valid, y_pred, types_valid)
        get_logger().info('fold %d valid %f' % (n_fold+1, valid_score))
        
        df_scores = df_scores.append(pd.Series([valid_score], index=['valid_score']), ignore_index=True)
        df_pred.loc[valid_idx, 'proba'] = y_pred
        df_pred.loc[valid_idx, 'y_true'] = y_valid
        models.append(model)
        
        # TODO: back
        # break
    get_logger().info('CV score: %f' % df_scores.mean()[0])
    
    return models, df_scores, df_pred

def oof_predict(_models, _X):
    get_logger().info('Start oof_predict')
    y_pred = np.zeros(_X.shape[0])
        
    for i, model in enumerate(_models):
        get_logger().info('prediction: %d' % i)
        y_pred += model.predict(_X) / len(_models)
    
    get_logger().info('Finish oof_predict')
    return y_pred


def gen_model(_X):
    n_features = _X.shape[1]
    colsample_rate = max(0.1, math.sqrt(n_features)/n_features)
    
    _model = lgb.LGBMRegressor(
        learning_rate=0.2,
        n_estimators=2000,
        num_leaves=128,
        # min_child_weight=15, # good value: 0, 5, 15, 300
        min_child_samples=80,
        subsample=0.7,
        colsample_bytree=1, # colsample_rate,
        objective='regression',
        reg_lambda=0.1,
        reg_alpha=0.1,
        seed=2019
        )
    return _model

def preprocess(df, strct, mode, s_type=None):
    """
    Parameters
    ----------
    df: pd.DataFrame
        dataframe of train.csv or test.csv
    strct: pd.DataFrame
        dataframe of structures.csv
    mode: str
        'train' or 'predict'
    s_type: None or pd.Series
        'type' column (e.g. 1JHC, 2JHH).
        If mode is 'train', the s_type must be specified.
    """
    get_logger().info('Start preprocess()')
    df = add_1j(df)
    df = add_2j_center_atom(df)
    df = add_3j_center_atom(df)
    df = map_atom_info(df, strct, 0)
    df = map_atom_info(df, strct, 1)
    df = calc_dist(df)
    df = divide_type(df)
    df = feature_engineering(df)
    
    display(df.head(10))
    display(df.tail(10))
    
    # encode
    if mode == 'train':
        enc = Encoder()
        enc.fit(df, ['type', 'type_0', 'type_1', 
                     '2j_atom_center', '3j_atom_center'])
        joblib.dump(enc, ENCODER_PATH)
    elif mode == 'predict':
        get_logger().info('loading encoder from %s' % ENCODER_PATH)
        enc = joblib.load(ENCODER_PATH)
    df = enc.transform(df)
        
    use_features = [col for col in df.columns if col not in [TARGET, *CONTR_COLS]] #'fc', 'sd', 'dso', 'pso']]
    get_logger().info(use_features)
    df[use_features] = reduce_mem_usage(df[use_features])
    # TODO: back
    # df = add_scc_feature(df, 'fc', mode=mode, s_type=s_type)
    
    get_logger().info('Finish preprocess()')
    return df

def drop_uneffect_feature(df):
    """
    Drop uneffective features from dataframe
    """
    for col in df.columns:
        if len(df[col].unique()) == 1:
            df.drop(col, axis=1, inplace=True)
    return df

"""### fermi constant"""

class CNTR:
    """Model to predict fc/sd/pso/dso columns"""
    
    def __init__(self, y_col):
        self.y_col = y_col
        
    def train(self, df_org, scc, s_type):
        """
        Parameters
        ----------
        s_type: pd.Series
            'type' column (e.g. 1JHC, 2JHH)
        """
        df = df_org.copy()
        # Merge
        key_cols = ['molecule_name', 'atom_index_0', 'atom_index_1']
        df = df.merge(scc[key_cols + [self.y_col]], how='left', on=key_cols)
        
        # drop unnecessary cols        
        df = drop_col(df)        
        
        y = df[self.y_col].copy()        
        df.drop([TARGET, self.y_col], axis=1, inplace=True)
        X = df
        
        display(X.head())
        display(y.head())
        models, scores, y_pred = oof_train(X, y, s_type)
        
        # save model
        joblib.dump(models, MID_MODEL_PATH, compress=3)
        
        self.models_ = models
        self.scores_ = scores
        self.y_pred_ = y_pred
        
    def predict(self, df_org):    
        y_pred = np.zeros(df_org.shape[0])
        
        X = df_org.copy()
        X = drop_col(X)
        
        display(X.head())
        # X = self.preprocess(df_org)
        for model in self.models_:            
            y_pred += model.predict(X) / len(models)
        
        return y_pred
    
    def load_model(self):
        # load pkl by joblib
        self.models_ = joblib.load(MID_MODEL_PATH)

def add_scc_feature(df, cntr_name, mode, s_type=None):
    """
    Parameters
    ----------
    cntr_name: str
        'fc', 'sd', 'pso' or 'dso'
    mode: str
        'train' or 'predict'
    s_type: None or pd.Series
        'type' column (e.g. 1JHC, 2JHH).
        If mode is 'train', the s_type must be specified.
    """
    add_feature = '%s_pred' % cntr_name
    cntr = CNTR(cntr_name)
    if mode == 'train': 
        assert s_type is not None, 's_type must be specified.'
        
        get_logger().info('start loading scalar_coupling_contributions')
        scc = pd.read_csv(INPUT + 'scalar_coupling_contributions.csv')
        get_logger().info('finished loading scalar_coupling_contributions')
        
        # train contribution(fc/sd/pso/dso)
        cntr.train(df, scc, s_type)
    
        display(cntr.y_pred_.head())
        df[add_feature] = cntr.y_pred_
    elif mode == 'predict':
        cntr.load_model()
        y_pred = cntr.predict(df)
        df[add_feature] = y_pred
    
    return df

"""## Train"""

df_train = pd.read_csv(TRAIN_PATH)
df_strct = pd.read_csv(INPUT + 'structures.csv')

# TODO: remove
# df_train = df_train[(df_train['type']=='1JHC') | (df_train['type']=='1JHN')]

def train_single_model(df, strct):
    # TODO: back
    df = df.head(10000)

    s_type = df['type'].copy()

    df = preprocess(df, strct, mode='train', s_type=s_type)
    df = drop_col(df)

    y = df[TARGET].copy()
    df.drop([TARGET], axis=1, inplace=True)
    X = df
    
    display(X.head())
    display(y.head())
    models, df_scores, df_pred = oof_train(X, y, s_type)

    joblib.dump(models, MODEL_PATH, compress=3)
    
    return models, df_scores, df_pred

class LGBM:
    def __init__(self, target_col):
        self.target_col = target_col
        self.model_dict = {}
        self.score_dict = {}
        self.pred_dict = {}
    
    def train(self, df, s_type):
        self.cols = df.columns.tolist()
        
        # TODO: back
        coupling_types = s_type.unique()
        # coupling_types = ['1JHC']
        for coup_type in coupling_types:
            get_logger().info('Starting train model(%s %s)' % (self.target_col, coup_type))
            is_the_type = (s_type == coup_type)        
            df_type = df[is_the_type.values]

            y = df_type[self.target_col]
            # df_type.drop([self.target_col], axis=1, inplace=True)
            df_type.drop(CONTR_COLS + [TARGET], axis=1, inplace=True)
            X = df_type
            X = drop_uneffect_feature(X)

            get_logger().info('features(%s): %s' % (coup_type, str(X.columns.tolist())))
            display(X.head())
            display(y.head())
            models, df_scores, df_pred = oof_train(X, y, _types=s_type[is_the_type].reset_index(drop=True))

            self.model_dict[coup_type] = models
            self.score_dict[coup_type] = df_scores
            self.pred_dict[coup_type] = df_pred                     
    
    def predict(self, df, s_type, df_submit):
        # df = df.head(10000)        
                
        # coupling_types = ['1JHC']
        coupling_types = s_type.unique()
        print(coupling_types)
        for coup_type in coupling_types:

            models = self.model_dict[coup_type]

            get_logger().info('Starting predict target(%s %s)' % (self.target_col, coup_type))
            is_the_type = (s_type == coup_type)
            df_type = df[is_the_type]

            X = df_type
            X = drop_uneffect_feature(X)        

            display(X.head())  
            y_pred = oof_predict(models, X)        

            df_submit.loc[is_the_type, self.target_col] = y_pred        
        
        return df_submit

def train_models_each_type(df, strct, use_preprocess_data):
    # TODO:back
    # df = df.head(100000)
    
    get_logger().info('Data size: %s' % str(df.shape))
    
    if use_preprocess_data:
        df = joblib.load(PREPROCESS + 'df_preprocessed.pkl')
    else:
        df_scc = pd.read_csv(INPUT + 'scalar_coupling_contributions.csv')
        df = df.merge(df_scc[MERGE_KEY + CONTR_COLS], on=MERGE_KEY, how='left')    

        s_type = df['type'].copy()

        df = preprocess(df, strct, mode='train', s_type=s_type)
        df = drop_col(df)
        
        joblib.dump(df, PREPROCESS + 'df_preprocessed.pkl', compress=3)
    
    '''
    model_dict = {}
    score_dict = {}
    pred_dict = {}
    coupling_types = s_type.unique()
    for coup_type in coupling_types:
        get_logger().info('Starting train model(%s)' % coup_type)
        is_the_type = (s_type == coup_type)        
        df_type = df[is_the_type.values]
                
        y = df_type[TARGET]
        df_type.drop([TARGET], axis=1, inplace=True)
        X = df_type
        X = drop_uneffect_feature(X)
        
        get_logger().info('features(%s): %s' % (coup_type, str(X.columns.tolist())))
        display(X.head())
        display(y.head())
        models, df_scores, df_pred = oof_train(X, y, _types=s_type[is_the_type].reset_index(drop=True))
        
        model_dict[coup_type] = models
        score_dict[coup_type] = df_scores
        pred_dict[coup_type] = df_pred
    return model_dict, score_dict, pred_dict
    '''
    models = {}
    for target in [TARGET]:# CONTR_COLS:
    # for target in CONTR_COLS:
        model = LGBM(target)
        model.train(df, s_type)
        models[target] = model
        
        model_file = 'model_%s.pkl' % target        
        joblib.dump(model, model_file, compress=3)
    
    get_logger().info('validate sum of fc sd pso dso')
    # coupling_types = ['1JHC']
    coupling_types = s_type.unique()
    for coup_type in coupling_types:
        is_the_type = (s_type == coup_type)
        y_true = df.loc[is_the_type, TARGET].values
        
        y_pred = np.zeros(len(y_true))
        for target in [TARGET]: # CONTR_COLS:
        # for target in CONTR_COLS:
            model = models[target]
            df_pred = model.pred_dict[coup_type]
            y_pred += df_pred['proba'].values
        
        print(y_true[0:10])
        print(y_pred[0:10])
        
        y_true = pd.Series(y_true)
        y_pred = pd.Series(y_pred)
        valid_score = group_mean_log_mae(y_true, y_pred, s_type)
        get_logger().info('valid score(fc+sd+pso+dso %s): %f' % (coup_type, valid_score))
    return models

# models, df_scores, df_pred = train_single_model(df_train, df_strct)
models = train_models_each_type(df_train, df_strct, USE_PREPROCESS_DATA)

models[TARGET].pred_dict['1JHC'].head()

score = 0
for j_type, df_score in models[TARGET].score_dict.items():
    print(j_type)    
    score_each_type = np.mean(df_score.values)
    print(score_each_type)
    score += score_each_type / 8
print(score)

"""### Check training result"""

# sns.distplot(df_pred['proba'])

def feat_importance(_models, _X, _imp_type='gain'):
    df_imp = pd.DataFrame(index=_X.columns)
    for i, model in enumerate(_models):
        df_imp[i] = model.booster_.feature_importance(importance_type=_imp_type)

    df_imp = df_imp.apply(lambda x: x/sum(x))
    df_imp['imp_mean'] = df_imp[list(range(len(models)))].mean(axis=1)
    df_imp['imp_std'] = df_imp[list(range(len(models)))].std(axis=1)
    sorted_imp = df_imp.sort_values(by='imp_mean', ascending=False)
    return sorted_imp

# imp = feat_importance(model_dict['1JHC'], X, _imp_type='gain')
# imp.head(100)

"""## Predict"""

df_test = pd.read_csv(TEST_PATH)
df_strct = pd.read_csv(INPUT + 'structures.csv')

def predict_single(df, strct):
    models = joblib.load(MODEL_PATH)

    df_submit = df[['id']].copy()
    df = preprocess(df, strct, mode='predict')
    X = drop_col(df)
    display(X.head())
    
    X.to_csv('test_prepro.csv', index=False)
    
    y_pred = oof_predict(models, X)
    df_submit['scalar_coupling_constant'] = y_pred
    
    return df_submit

def predict_each_type(df, strct):
    df = df.head(10000)
    # model_dict = joblib.load(MODEL_PATH)
    
    s_type = df['type'].copy()
    df_submit = df[['id']].copy()
    
    df = preprocess(df, strct, mode='predict')
    df = drop_col(df)    
    
    '''
    coupling_types = s_type.unique()
    print(coupling_types)
    for coup_type in coupling_types:
        
        models = model_dict[coup_type]
        
        get_logger().info('Starting predict target(%s)' % coup_type)
        is_the_type = (s_type == coup_type)
        df_type = df[is_the_type]
                      
        X = df_type
        X = drop_uneffect_feature(X)        
        
        display(X.head())  
        y_pred = oof_predict(models, X)        
        
        df_submit.loc[is_the_type, 'scalar_coupling_constant'] = y_pred
    '''
    
    df_submit[TARGET] = 0
    # for target in CONTR_COLS: # ['fc', 'sd', 'pso', 'dso']: 
    for target in [TARGET]: 
        get_logger().info('Start prediction: %s' % target)
        model_file = 'model_%s.pkl' % target
        model = joblib.load(model_file)
                
        df_submit_each_target = model.predict(df, s_type, df_submit)                              
        df_submit[TARGET] += df_submit_each_target[target]
    
    display(df_submit.head())
    print((df_submit[TARGET].isnull()).sum())
    return df_submit

df_submit = predict_each_type(df_test, df_strct)

display(df_submit.head())
df_submit[['id', TARGET]].to_csv('submission.csv', index=False)

df_submit.shape

