#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jul  2 09:59:06 2020

@author: semvijverberg
"""


import os, inspect, sys
import matplotlib as mpl
if sys.platform == 'linux':
    mpl.use('Agg')
    n_cpu = 4
else:
    n_cpu = 2
# else:
#     # Optionally set font to Computer Modern to avoid common missing font errors
#     mpl.rc('font', family='serif', serif='cm10')

#     mpl.rc('text', usetex=True)
#     mpl.rcParams['text.latex.preamble'] = [r'\boldmath']
import numpy as np
from time import time
import cartopy.crs as ccrs ; import matplotlib.pyplot as plt
import matplotlib
import pandas as pd
import xarray as xr
import csv
from joblib import Parallel, delayed
# import sklearn.linear_model as scikitlinear
import argparse

user_dir = os.path.expanduser('~')
os.chdir(os.path.join(user_dir,
                      'surfdrive/Scripts/RGCPD/publications/paper_Raed/'))
curr_dir = os.path.join(user_dir, 'surfdrive/Scripts/RGCPD/RGCPD/')
main_dir = '/'.join(curr_dir.split('/')[:-2])
RGCPD_func = os.path.join(main_dir, 'RGCPD')
assert main_dir.split('/')[-1] == 'RGCPD', 'main dir is not RGCPD dir'
cluster_func = os.path.join(main_dir, 'clustering/')
fc_dir = os.path.join(main_dir, 'forecasting')

if cluster_func not in sys.path:
    sys.path.append(main_dir)
    sys.path.append(RGCPD_func)
    sys.path.append(cluster_func)
    sys.path.append(fc_dir)

path_raw = user_dir + '/surfdrive/ERA5/input_raw'


from RGCPD import RGCPD
from RGCPD import BivariateMI
import class_BivariateMI
import func_models as fc_utils
import functions_pp, find_precursors
import plot_maps;
import wrapper_PCMCI


target_datasets = ['USDA_Soy', 'USDA_Maize']#, 'GDHY_Soy']
seeds = seeds = [1] # [1,2,3,4,5]
yrs = ['1950, 2019'] # ['1950, 2019', '1960, 2019', '1950, 2009']
add_prev = [True, False]
feature_sel = [True, False]
combinations = np.array(np.meshgrid(target_datasets,
                                    seeds,
                                    yrs,
                                    add_prev,
                                    feature_sel)).T.reshape(-1,5)
i_default = 4


def parseArguments():
    # Create argument parser
    parser = argparse.ArgumentParser()

    # Optional arguments
    parser.add_argument("-i", "--intexper", help="intexper", type=int,
                        default=i_default)
    # Parse arguments
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    args = parseArguments()
    out = combinations[args.intexper]
    target_dataset = out[0]
    seed = int(out[1])
    start_end_year = (int(out[2][:4]), int(out[2][-4:]))
    feature_selection = out[3] == 'True'
    add_previous_periods = out[4] == 'True'
    print(f'arg {args.intexper} {out}')
else:
    out = combinations[i_default]
    target_dataset = out[0]
    seed = int(out[1])
    start_end_year = (int(out[2][:4]), int(out[2][-4:]))



if target_dataset == 'GDHY_Soy':
    # GDHY dataset 1980 - 2015
    TVpath = os.path.join(main_dir, 'publications/paper_Raed/clustering/q50_nc4_dendo_707fb.nc')
    cluster_label = 3
    name_ds='ts'
    # start_end_year = (1980, 2015)
elif target_dataset == 'USDA_Soy':
    # USDA dataset 1950 - 2019
    TVpath =  os.path.join(main_dir, 'publications/paper_Raed/data/usda_soy_spatial_mean_ts.nc')
    name_ds='Soy_Yield' ; cluster_label = ''
    # TVpath = '/Users/semvijverberg/surfdrive/VU_Amsterdam/GDHY_MIRCA2000_Soy/USDA/ts_spatial_avg_midwest.h5'
    # TVpath = '/Users/semvijverberg/surfdrive/VU_Amsterdam/GDHY_MIRCA2000_Soy/USDA/ts_spatial_avg.h5'
    # name_ds='USDA_Soy'
    # start_end_year = (1950, 2019)
elif target_dataset == 'USDA_Maize':
    # USDA dataset 1950 - 2019
    TVpath =  os.path.join(main_dir, 'publications/paper_Raed/data/usda_maize_spatial_mean_ts.nc')
    name_ds='Maize_Yield' ; cluster_label = None
    # start_end_year = (1950, 2019)



calc_ts='region mean' # pattern cov
alpha_corr = .05
method     = 'ranstrat_10' ;
n_boot = 2000


append_main = target_dataset
path_out_main = os.path.join(user_dir, 'surfdrive', 'output_paper3')
PacificBox = (130,265,-10,60)
GlobalBox  = (-180,360,-10,60)
USBox = (225, 300, 20, 60)


save = True


#%% run RGPD

list_of_name_path = [(cluster_label, TVpath),
                       ('sst', os.path.join(path_raw, 'sst_1950-2019_1_12_monthly_1.0deg.nc')),
                      # ('z500', os.path.join(path_raw, 'z500_1950-2019_1_12_monthly_1.0deg.nc')),
                       ('smi', os.path.join(path_raw, 'SM_ownspi_gamma_2_1950-2019_1_12_monthly_1.0deg.nc'))]
                      # ('swvl1', os.path.join(path_raw, 'swvl1_1950-2019_1_12_monthly_1.0deg.nc'))]

def pipeline(lags, periodnames):

    if int(lags[0][0].split('-')[-2]) > 7: # first month after july
        crossyr = True
    else:
        crossyr = False

    SM_lags = np.array([[l[0].replace(l[0].split('-')[-2], l[1].split('-')[-2], 1), l[1]] for l in lags])
    list_for_MI   = [BivariateMI(name='sst', func=class_BivariateMI.corr_map,
                                alpha=alpha_corr, FDR_control=True,
                                kwrgs_func={},
                                distance_eps=400, min_area_in_degrees2=7,
                                calc_ts=calc_ts, selbox=GlobalBox,
                                lags=lags, group_split=True,
                                use_coef_wghts=True),
                      BivariateMI(name='smi', func=class_BivariateMI.corr_map,
                                 alpha=.05, FDR_control=True,
                                 kwrgs_func={},
                                 distance_eps=300, min_area_in_degrees2=4,
                                 calc_ts=calc_ts, selbox=USBox,
                                 lags=SM_lags, use_coef_wghts=True)]


    rg = RGCPD(list_of_name_path=list_of_name_path,
               list_for_MI=list_for_MI,
               list_import_ts=None,
               start_end_TVdate=None,
               start_end_date=None,
               start_end_year=start_end_year,
               tfreq=None,
               path_outmain=path_out_main)


    subfoldername = target_dataset+'_'.join(['', str(method),
                                             's'+ str(seed)] +
                                            list(np.array(start_end_year, str)))


    rg.pp_precursors(detrend=[True, {'tp':False, 'smi':False, 'swvl1':False, 'swvl3':False}],
                     anomaly=[True, {'tp':False, 'smi':False, 'swvl1':False, 'swvl3':False}],
                     auto_detect_mask=[False, {'swvl1':True, 'swvl2':True}])
    if crossyr:
        TV_start_end_year = (1951, 2019)
    else:
        TV_start_end_year = (1950, 2019)

    kwrgs_core_pp_time = {'start_end_year': TV_start_end_year}
    rg.pp_TV(name_ds=name_ds, detrend=True, ext_annual_to_mon=False,
             kwrgs_core_pp_time=kwrgs_core_pp_time)
    rg.traintest(method, seed=seed, subfoldername=subfoldername)

    #%%
    sst = rg.list_for_MI[0]
    rg.calc_corr_maps('sst')
    sst.corr_xr['lag'] = ('lag', periodnames)

    #%%
    SM = rg.list_for_MI[1]
    rg.calc_corr_maps('smi')
    SM.corr_xr['lag'] = ('lag', periodnames)
    #%%



    sst.distance_eps = 250 ; sst.min_area_in_degrees2 = 4
    rg.cluster_list_MI('sst')

    # check if west-Atlantic is a seperate region, otherwise split region 1
    df_labels = find_precursors.labels_to_df(sst.prec_labels)
    dlat = df_labels['latitude'] - 29
    dlon = df_labels['longitude'] - 290
    zz = pd.concat([dlat.abs(),dlon.abs()], axis=1)
    if zz.query('latitude < 10 & longitude < 10').size==0:
        print('Splitting region west-Atlantic')
        largest_regions = df_labels['n_gridcells'].idxmax()
        split = find_precursors.split_region_by_lonlat
        sst.prec_labels, _ = split(sst.prec_labels.copy(), label=int(largest_regions),
                                kwrgs_mask_latlon={'upper_right': (263, 16)})

    merge = find_precursors.merge_labels_within_lonlatbox

    # # Ensure that what is in Atlantic is one precursor region
    lonlatbox = [263, 315, 17, 30]
    sst.prec_labels = merge(sst, lonlatbox)
    # Indonesia_oceans = [110, 150, 0, 10]
    # sst.prec_labels = merge(sst, Indonesia_oceans)
    Japanese_sea = [100, 150, 30, 50]
    sst.prec_labels = merge(sst, Japanese_sea)
    Mediterrenean_sea = [0, 45, 30, 50]
    sst.prec_labels = merge(sst, Mediterrenean_sea)
    East_Tropical_Atlantic = [330, 20, -10, 10]
    sst.prec_labels = merge(sst, East_Tropical_Atlantic)
    rg.quick_view_labels('sst', min_detect_gc=1, save=save)

    #%%
    SM = rg.list_for_MI[1]
    SM.distance_eps = 280 ; SM.min_area_in_degrees2 = 4
    rg.cluster_list_MI('smi')

    lonlatbox = [220, 240, 25, 55] # eastern US
    SM.prec_labels = merge(SM, lonlatbox)
    lonlatbox = [270, 280, 25, 45] # mid-US
    SM.prec_labels = merge(SM, lonlatbox)

    rg.quick_view_labels('smi', min_detect_gc=1, save=save)

#%%

    rg.get_ts_prec()
    rg.df_data = rg.df_data.rename({rg.df_data.columns[0]:target_dataset},axis=1)
    # # fill first value of smi (NaN because of missing December when calc smi
    # # on month februari).
    # keys = [k for k in rg.df_data.columns if k.split('..')[-1]=='smi']
    # rg.df_data[keys] = rg.df_data[keys].fillna(value=0)

    #%% Causal Inference

    def feature_selection_CondDep(df_data, keys, z_keys=None, alpha_CI=.05, x_lag=0, z_lag=0):

        # Feature selection Cond. Dependence
        keys = list(keys) # must be list
        if z_keys is None:
            z_keys = keys
        corr, pvals = wrapper_PCMCI.df_data_Parcorr(df_data.copy(), keys=keys,
                                                    z_keys=z_keys, z_lag=z_lag)
        # removing all keys that are Cond. Indep. in each trainingset
        keys_dict = dict(zip(range(rg.n_spl), [keys]*rg.n_spl)) # all vars
        for s in rg.df_splits.index.levels[0]:
            for k_i in keys:
                onekeyCI = (np.nan_to_num(pvals.loc[k_i][s],nan=alpha_CI) > alpha_CI).mean()>0
                keyisNaN = np.isnan(pvals.loc[k_i][s]).all()
                if onekeyCI or keyisNaN:
                    k_ = keys_dict[s].copy() ; k_.pop(k_.index(k_i))
                    keys_dict[s] = k_

        return corr, pvals, keys_dict.copy()


    regress_autocorr_SM = False
    unique_keys = np.unique(['..'.join(k.split('..')[1:]) for k in rg.df_data.columns[1:-2]])
    # select the causal regions from analysys in Causal Inferred Precursors


    print('Start Causal Inference')
    list_pvals = [] ; list_corr = []
    for k in unique_keys:
        z_keys = [z for z in rg.df_data.columns[1:-2] if k not in z]

        for mon in periodnames:
            keys = [mon+ '..'+k]
            if regress_autocorr_SM and 'sm' in k:
                z_keys = [z for z in rg.df_data.columns[1:-2] if keys[0] not in z]


            if keys[0] not in rg.df_data.columns:
                continue
            out = feature_selection_CondDep(rg.df_data.copy(), keys=keys,
                                            z_keys=z_keys, alpha_CI=.05)
            corr, pvals, keys_dict = out
            list_pvals.append(pvals.max(axis=0, level=0))
            list_corr.append(corr.mean(axis=0, level=0))


    rg.df_pvals = pd.concat(list_pvals,axis=0)
    rg.df_corr = pd.concat(list_corr,axis=0)

    rg_list.append(rg)
    return rg


# pipeline(lags=lags_april, periodnames=periodnames_april)

#%%
if __name__ == '__main__':

    lags_july = np.array([['1950-12-01', '1951-01-01'],# DJ
                          ['1951-02-01', '1951-03-01'],# FM
                          ['1951-04-01', '1951-05-01'],# AM
                          ['1951-06-01', '1951-07-01'] # JJ
                          ])
    periodnames_july = ['Jan', 'March', 'May', 'July']

    lags_june = np.array([['1950-11-01', '1950-12-01'],# FM
                          ['1951-01-01', '1951-02-01'],# FM
                          ['1951-03-01', '1951-04-01'],# AM
                          ['1951-05-01', '1951-06-01'] # JJ
                          ])
    periodnames_june = ['Dec', 'Feb', 'April', 'June']

    lags_may = np.array([['1950-10-01', '1950-11-01'],# ON
                         ['1950-12-01', '1951-01-01'],# DJ
                         ['1951-02-01', '1951-03-01'],# FM
                         ['1951-04-01', '1951-05-01'] # AM
                         ])
    periodnames_may = ['Nov', 'Jan', 'Mar', 'May']

    lags_april = np.array([['1950-09-01', '1950-10-01'],# SO
                           ['1950-11-01', '1950-12-01'],# ND
                           ['1951-01-01', '1951-02-01'],# JF
                           ['1951-03-01', '1951-04-01'] # MA
                           ])
    periodnames_april = ['Oct', 'Dec', 'Feb', 'April']

    lag_list = [lags_july, lags_june, lags_may, lags_april]
    periodnames_list = [periodnames_july, periodnames_june,
                        periodnames_may, periodnames_april]


    futures = [delayed(pipeline)(lags, periodnames) for lags, periodnames in zip(lag_list, periodnames_list)]
    rg_list = Parallel(n_jobs=n_cpu, backend='loky')(futures)


#%%
lags_june = np.array([['0-11-01', '0-12-01'],# FM
                      ['1-01-01', '1-02-01'],# FM
                      ['1-03-01', '1-04-01'],# AM
                      ['1-05-01', '1-06-01'] # JJ
                      ])
periodnames_june = ['Dec', 'Feb', 'April', 'June']

#%%

from sklearn.linear_model import RidgeCV
select_str_SM = False
mean_SST = True
def get_df_mean_SST(rg, mean_SST=True, select_str_SM=False, n_strongest=4, weights=True,
                    labels=None):
    alpha_CI = .05
    periodnames = list(rg.list_for_MI[0].corr_xr.lag.values)
    df_pvals = rg.df_pvals.copy()
    df_corr  = rg.df_corr.copy()
    unique_keys = np.unique(['..'.join(k.split('..')[1:]) for k in rg.df_data.columns[1:-2]])
    if labels is not None:
        unique_keys = [k for k in unique_keys if k in labels]

    # dict with strongest mean parcorr over growing season
    mean_SST_list = []
    keys_dict = {s:[] for s in range(rg.n_spl)} ;
    keys_dict_meansst = {s:[] for s in range(rg.n_spl)} ;
    for s in range(rg.n_spl):
        mean_SST_list_s = []
        sign_s = df_pvals[s][df_pvals[s] <= alpha_CI].dropna(axis=0, how='all')
        for uniqk in unique_keys:
            # uniqk = '1..sst'
            # region label (R) for each month in split (s)
            keys_mon = [mon+ '..'+uniqk for mon in periodnames]
            # significant region label (R) for each month in split (s)
            keys_mon_sig = [k for k in keys_mon if k in sign_s.index] # check if sig.
            if mean_SST and 'sst' in uniqk and len(keys_mon_sig)!=0:
                # calculate mean over n strongest SST timeseries
                if len(keys_mon_sig) > 1:
                    meanparcorr = df_corr.loc[keys_mon_sig][[s]].squeeze().sort_values()
                    keys_str = meanparcorr.index[-n_strongest:]
                else:
                    keys_str  = keys_mon_sig
                if weights:
                    df_train = functions_pp.get_df_train(rg.df_data,
                                                          cols=[target_dataset] + list(keys_str),
                                                          s=s)
                    kwrgs = {'alphas':[1E-20, 1E-5, 1E-2, .1, 1, 10, 50, 100]}
                    _m = RidgeCV(**kwrgs).fit(df_train[keys_str],
                                                            df_train[target_dataset])
                    df_mean = pd.Series(_m.predict(rg.df_data.loc[s][keys_str].copy()),
                                            index=rg.df_data.loc[s].index)
                else:
                    df_mean = rg.df_data.loc[s][keys_str].copy().mean(1)
                month_strings = [k.split('..')[0] for k in sorted(keys_str)]
                df_mean.name = ''.join(month_strings) + '..'+uniqk
                keys_dict_meansst[s].append( df_mean.name )
                mean_SST_list_s.append(df_mean)
            elif mean_SST and 'smi' in uniqk and len(keys_mon_sig)!=0:
                # use all SM timeseries (for each month)
                mean_SST_list_s.append(rg.df_data.loc[s][keys_mon_sig].copy())
                keys_dict_meansst[s] = keys_dict_meansst[s] + keys_mon_sig
            # select strongest
            if len(keys_mon_sig) != 0 and 'sst' in uniqk:
                # appending keys_dict for plotting causal regions
                df_corr.loc[keys_mon_sig].mean()
                keys_dict[s].append( df_corr.loc[keys_mon_sig][s].idxmax() )
            if select_str_SM and len(keys_mon_sig) != 0 and 'sm' in uniqk:
                # use only strongest SM region
                df_corr.loc[keys_mon_sig].mean()
                keys_dict[s].append( df_corr.loc[keys_mon_sig][s].idxmax() )
            elif select_str_SM==False and len(keys_mon_sig) != 0 and 'sm' in uniqk:
                # use all SM region
                keys_dict[s] = keys_dict[s] + keys_mon_sig
        df_s = pd.concat(mean_SST_list_s, axis=1)
        mean_SST_list.append(df_s)
    df_mean_SST = pd.concat(mean_SST_list, keys=range(rg.n_spl))
    df_mean_SST = df_mean_SST.merge(rg.df_splits.copy(),
                                    left_index=True, right_index=True)
    return df_mean_SST, keys_dict_meansst


#%%
months = ['Mar', 'April', 'May', 'June','July', 'August']
list_verification = [] ; list_prediction = []
for i, rg in enumerate(rg_list):

    df_data, keys_dict = get_df_mean_SST(rg, n_strongest=3)
    last_month = list(rg.list_for_MI[0].corr_xr.lag.values)[-1]
    fc_month = months[months.index(last_month)+1]
    from sklearn.linear_model import Ridge
    from stat_models_cont import ScikitModel

    # fcmodel = ScikitModel(RandomForestRegressor, verbosity=0)
    # kwrgs_model={'n_estimators':200,
    #             'max_depth':[2,5,7],
    #             'scoringCV':'neg_mean_squared_error',
    #             'oob_score':True,
    #             'min_samples_leaf':2,
    #             'random_state':0,
    #             'max_samples':.6,
    #             'n_jobs':1}
    fcmodel = ScikitModel(RidgeCV, verbosity=0)
    kwrgs_model = {'scoring':'neg_mean_absolute_error',
                    'alphas':np.concatenate([[1E-20],np.logspace(-5,0, 6),
                                              np.logspace(.01, 2.5, num=10)]), # large a, strong regul.
                    'normalize':False,
                    'fit_intercept':False,
                    # 'store_cv_values':True}
                    'kfold':5}

    fcmodel = ScikitModel(Ridge, verbosity=0)
    kwrgs_model = {'scoringCV':'neg_mean_absolute_error',
                    'alpha':list(np.concatenate([[1E-20],np.logspace(-5,0, 6),
                                              np.logspace(.01, 2.5, num=10)])), # large a, strong regul.
                    'normalize':False,
                    'fit_intercept':False,
                    'kfold':5}


    # target
    fc_mask = rg.df_data.iloc[:,-1].loc[0]
    target_ts = rg.df_data.iloc[:,[0]].loc[0][fc_mask]
    target_ts = (target_ts - target_ts.mean()) / target_ts.std()
    # metrics
    RMSE_SS = fc_utils.ErrorSkillScore(constant_bench=float(target_ts.mean())).RMSE
    MAE_SS = fc_utils.ErrorSkillScore(constant_bench=float(target_ts.mean())).MAE
    score_func_list = [RMSE_SS, fc_utils.corrcoef, MAE_SS]
    metric_names = [s.__name__ for s in score_func_list]


    lag_ = 0 ;
    prediction_tuple = rg.fit_df_data_ridge(df_data=df_data,
                                            keys=keys_dict,
                                            target=target_ts,
                                            tau_min=0, tau_max=0,
                                            kwrgs_model=kwrgs_model,
                                            fcmodel=fcmodel,
                                            transformer=None)
    predict, weights, models_lags = prediction_tuple
    prediction = predict.rename({predict.columns[0]:'target',
                                 lag_:last_month}, axis=1)
    prediction_tuple = (prediction, weights, models_lags)
    list_prediction.append(prediction_tuple)
    rg.prediction_tuple = prediction_tuple

    weights_norm = weights.mean(axis=0, level=1)
    # weights_norm.div(weights_norm.max(axis=0)).T.plot(kind='box', figsize=(15,5))


    verification_tuple = fc_utils.get_scores(prediction,
                                             rg.df_data.iloc[:,-2:],
                                             score_func_list,
                                             n_boot=2000,
                                             blocksize=1,
                                             rng_seed=1)
    df_train_m, df_test_s_m, df_test_m, df_boot = verification_tuple


    m = models_lags[f'lag_{lag_}'][f'split_{0}']
    plt.plot(kwrgs_model['alpha'], m.cv_results_['mean_test_score'])
    plt.axvline(m.best_params_['alpha']) ; plt.show() ; plt.close()

    df_test = functions_pp.get_df_test(predict.rename({lag_:'causal'}, axis=1),
                                        df_splits=rg.df_splits)
    list_verification.append(verification_tuple)
    rg.verification_tuple = verification_tuple


#%%
df_scores = [] ; df_boot = []
for i, rg in enumerate(rg_list):
    df_scores.append(rg.verification_tuple[2])
    df_boot.append(rg.verification_tuple[3])
df_scores = pd.concat(df_scores, axis=1)
df_boot = pd.concat(df_boot, axis=1)

orientation = 'vertical'
alpha = .05
metrics_cols = ['corrcoef', 'MAE']
rename_m = {'corrcoef': 'Corr. coeff.', 'RMSE':'RMSE-SS',
            'MAE':'MAE-SS', 'CRPSS':'CRPSS'}

if orientation=='vertical':
    f, ax = plt.subplots(len(metrics_cols),1, figsize=(6, 5*len(metrics_cols)),
                     sharex=True) ;
else:
    f, ax = plt.subplots(1,len(metrics_cols), figsize=(6.5*len(metrics_cols), 5),
                     sharey=False) ;

c1, c2 = '#3388BB', '#EE6666'
for i, m in enumerate(metrics_cols):
    labels = df_scores.columns.levels[0]
    # normal SST
    ax[i].plot(labels, df_scores.reorder_levels((1,0), axis=1).loc[0][m].T,
            label='Forecast [SST+SM]',
            color=c2,
            linestyle='solid')
    ax[i].fill_between(labels,
                        df_boot.reorder_levels((1,0), axis=1)[m].quantile(1-alpha/2.),
                        df_boot.reorder_levels((1,0), axis=1)[m].quantile(alpha/2.),
                        edgecolor=c2, facecolor=c2, alpha=0.3,
                        linestyle='solid', linewidth=2)



    if m == 'corrcoef':
        ax[i].set_ylim(-.2,1)
    else:
        ax[i].set_ylim(-.15,.4)
    ax[i].axhline(y=0, color='black', linewidth=1)
    ax[i].tick_params(labelsize=16)
    if i == len(metrics_cols)-1 and orientation=='vertical':
        ax[i].set_xlabel('Forecast month', fontsize=18)
    elif orientation=='horizontal':
        ax[i].set_xlabel('Forecast month', fontsize=18)
    if i == 0:
        ax[i].legend(loc='lower right', fontsize=14)
    ax[i].set_ylabel(rename_m[m], fontsize=18, labelpad=-4)


f.subplots_adjust(hspace=.1)
f.subplots_adjust(wspace=.2)
title = 'Verification Soy Yield forecast using SST and SMI'
if orientation == 'vertical':
    f.suptitle(title, y=.92, fontsize=18)
else:
    f.suptitle(title, y=.95, fontsize=18)
f_name = f'{method}_{seed}'
fig_path = os.path.join(rg.path_outsub1, f_name)+rg.figext
if save:
    plt.savefig(fig_path, bbox_inches='tight')


#%%
# =============================================================================
# Plot Causal Links
# =============================================================================
kwrgs_plotcorr_sst = {'row_dim':'lag', 'col_dim':'split','aspect':4, 'hspace':0,
                  'wspace':-.15, 'size':3, 'cbar_vert':0.05,
                  'map_proj':ccrs.PlateCarree(central_longitude=220),
                   'y_ticks':np.arange(-10,61,20), #'x_ticks':np.arange(130, 280, 25),
                  'title':'',
                  'title_fontdict':{'fontsize':16, 'fontweight':'bold'}}

kwrgs_plotcorr_SM = kwrgs_plotcorr_sst.copy()
kwrgs_plotcorr_SM.update({'aspect':2, 'hspace':0.2,
                          'wspace':0, 'size':3, 'cbar_vert':0.02})

#%%

def plot_regions(rg, save=save):
    # Get ConDepKeys
    df_pvals = rg.df_pvals.copy()
    df_corr  = rg.df_corr.copy()
    periodnames = list(rg.list_for_MI[0].corr_xr.lag.values)

    alpha_CI = .05
    CondDepKeys = {} ;
    for i, mon in enumerate(periodnames):
        list_mon = []
        _keys = [k for k in df_pvals.index if mon in k] # month
        df_sig = df_pvals[df_pvals.loc[_keys] <= alpha_CI].dropna(axis=0, how='all') # significant

        for k in df_sig.index:
            corr_val = df_corr.loc[k].mean()
            RB = (df_pvals.loc[k]<alpha_CI).sum()
            list_mon.append((k, corr_val, RB))
        CondDepKeys[mon] = list_mon

    for ip, precur in enumerate(rg.list_for_MI):
        # ip=0; precur = rg.list_for_MI[ip]

        CDlabels = precur.prec_labels.copy()

        if precur.group_lag:
            CDlabels = xr.concat([CDlabels]*len(periodnames), dim='lag')
            CDlabels['lag'] = ('lag', periodnames)
            CDcorr = precur.corr_xr_.copy()
        else:
            CDcorr = precur.corr_xr.copy()
        textinmap = []
        MCIstr = CDlabels.copy()
        for i, month in enumerate(CondDepKeys):

            CDkeys = [k[0] for k in CondDepKeys[month] if k[0].split('..')[-1]==precur.name]
            MCIv = [k[1] for k in CondDepKeys[month] if k[0].split('..')[-1]==precur.name]
            RB = [k[2] for k in CondDepKeys[month] if k[0].split('..')[-1]==precur.name]
            region_labels = [int(l.split('..')[1]) for l in CDkeys if l.split('..')[-1] == precur.name]
            f = find_precursors.view_or_replace_labels
            CDlabels[:,i] = f(CDlabels[:,i].copy(), region_labels)
            MCIstr[:,i]   = f(CDlabels[:,i].copy(), region_labels,
                              replacement_labels=MCIv)
            # get text on robustness:
            if len(CDkeys) != 0:
                temp = []
                df_labelloc = find_precursors.labels_to_df(CDlabels[:,i])
                for q, k in enumerate(CDkeys):
                    l = int(k.split('..')[1])
                    lat, lon = df_labelloc.loc[l].iloc[:2].values.round(1)
                    if lon > 180: lon-360
                    count = rg._df_count[k]
                    text = f'{int(RB[q])}/{count}'
                    temp.append([lon+10,lat+5, text, {'fontsize':15,
                                                   'bbox':dict(facecolor='white', alpha=0.8)}])
                textinmap.append([(i,0), temp])

        # mask = (np.isnan(CDlabels)).astype(bool)
        if ip == 0:
            kwrgs_plot = kwrgs_plotcorr_sst.copy()
        elif ip == 1:
            kwrgs_plot = kwrgs_plotcorr_SM.copy()
        # labels plot
        plot_maps.plot_labels(CDlabels.mean(dim='split'), kwrgs_plot=kwrgs_plot)
        if save:
            if method == 'pcmci':
                dirpath = rg.path_outsub2
            else:
                dirpath = rg.path_outsub1
            plt.savefig(os.path.join(dirpath,
                                  f'{precur.name}_eps{precur.distance_eps}'
                                  f'minarea{precur.min_area_in_degrees2}_aCI{alpha_CI}_labels_'
                                  f'{periodnames[-1]}'+rg.figext),
                         bbox_inches='tight')

        # MCI values plot
        kwrgs_plot.update({'clevels':np.arange(-0.8, 0.9, .1),
                           'textinmap':textinmap})
        fig = plot_maps.plot_corr_maps(MCIstr.mean(dim='split'),
                                       mask_xr=np.isnan(MCIstr.mean(dim='split')).astype(bool),
                                       **kwrgs_plot)
        if save:
            fig.savefig(os.path.join(dirpath,
                                      f'{precur.name}_eps{precur.distance_eps}'
                                      f'minarea{precur.min_area_in_degrees2}_aCI{alpha_CI}_MCI_'
                                      f'{periodnames[-1]}'+rg.figext),
                        bbox_inches='tight')



for rg in rg_list:
    plot_regions(rg, save=save)

