#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Dec  5 12:17:25 2019

@author: semvijverberg
"""

import itertools, os, re
import numpy as np
import xarray as xr
#import datetime
import scipy
import pandas as pd
from statsmodels.sandbox.stats import multicomp
import functions_pp, core_pp
import find_precursors
from func_models import apply_shift_lag
from typing import Union
import uuid
flatten = lambda l: list(itertools.chain.from_iterable(l))

try:
    from tigramite.independence_tests import ParCorr
except:
    pass


class BivariateMI:

    def __init__(self, name, func=None, kwrgs_func={}, alpha: float=0.05,
                 FDR_control: bool=True, lags=np.array([1]),
                 lag_as_gap: bool=False, distance_eps: int=400,
                 min_area_in_degrees2=3, group_lag: bool=False,
                 group_split : bool=True, calc_ts='region mean',
                 selbox: tuple=None, use_sign_pattern: bool=False,
                 use_coef_wghts: bool=True, path_hashfile: str=None,
                 hash_str: str=None, dailytomonths: bool=False, verbosity=1):
        '''

        Parameters
        ----------
        name : str
            Name that links to a filepath pointing to a Netcdf4 file.
        func : function to apply to calculate the bivariate
            Mutual Informaiton (MI), optional
            The default is applying a correlation map.
        kwrgs_func : TYPE, optional
            DESCRIPTION. The default is {}.
        alpha : float, optional
            significance threshold
        FDR_control: bool, optional
            Control for multiple hypothesis testing
        lags : np.ndarray, optional
            lag w.r.t. the the target variable at which to calculate the MI.
            The default is np.array([1]).
        lag_as_gap : bool, optional
            Interpret the lag as days in between last day of precursor
            aggregation window and first day of target window.
        distance_eps : int, optional
            The maximum distance between two gridcells for one to be considered
            as in the neighborhood of the other, only gridcells with the same
            sign are grouped together.
            The default is 400.
        min_area_in_degrees2 : TYPE, optional
            The number of samples gridcells in a neighborhood for a
            region to be considered as a core point. The parameter is
            propotional to the average size of 1 by 1 degree gridcell.
            The default is 400.
        group_split : str, optional
            If True, then region labels will be equal between different train test splits.
            If False, splits will clustered separately.
            The default is 'together'.
        calc_ts : str, optional
            Choose 'region mean' or 'pattern cov'. If 'region mean', a
            timeseries is calculated for each label. If 'pattern cov', the
            spatial covariance of the whole pattern is calculated.
            The default is 'region_mean'.
        selbox : tuple, optional
            has format of (lon_min, lon_max, lat_min, lat_max)
        use_sign_pattern : bool, optional
            When calculating spatial covariance, do not use original pattern
            but focus on the sign of each region. Used for quantifying Rossby
            waves.
        use_coef_wghts : bool, optional
            When True, using (corr) coefficient values as weights when calculating
            spatial mean. (will always be area weighted).
        dailytomonths : bool, optional
            When True, the daily input data will be aggregated to monthly data,
            subsequently, the pre-processing steps are performed (detrend/anomaly).
        verbosity : int, optional
            Not used atm. The default is 1.

        Returns
        -------
        Initialization of the BivariateMI class

        '''
        self.name = name
        if func is None:
            self.func = corr_map
        else:
            self.func = func
        self._name = name + '_'+ self.func.__name__

        self.kwrgs_func = kwrgs_func

        self.alpha = alpha
        self.FDR_control = FDR_control
        #get_prec_ts & spatial_mean_regions
        self.calc_ts = calc_ts
        self.selbox = selbox
        self.use_sign_pattern = use_sign_pattern
        self.use_coef_wghts = use_coef_wghts
        if type(lags) is np.ndarray and type(lags[0]) is not np.ndarray:
            lags = np.array(lags, dtype=np.int16) # fix dtype
            self.lag_coordname = lags
        else:
            self.lag_coordname = np.arange(len(lags)) # for period_means
        self.lags = lags
        self.lag_as_gap = lag_as_gap

        self.dailytomonths = dailytomonths

        # cluster_DBSCAN_regions
        self.distance_eps = distance_eps
        self.min_area_in_degrees2 = min_area_in_degrees2
        self.group_split = group_split
        self.group_lag = group_lag
        self.verbosity = verbosity
        if hash_str is not None:
            assert path_hashfile is not None, 'Give path to search hashfile'
            self.load_files(self, path_hashfile=str, hash_str=str)

        return


    def bivariateMI_map(self, precur_arr, df_splits, RV): #
        #%%
        # precur_arr = self.precur_arr ; df_splits = rg.df_splits ; RV = rg.TV
        """
        This function calculates the correlation maps for precur_arr for different lags.
        Field significance is applied to test for correltion.
        RV_period: indices that matches the response variable time series
        alpha: significance level

        A land sea mask is assumed from settin all the nan value to True (masked).
        For xrcorr['mask'], all gridcell which are significant are not masked,
        i.e. bool == False
        """

        n_lags = len(self.lags)
        lags = self.lags
        self.df_splits = df_splits # add df_splits to self
        dates = self.df_splits.loc[0].index

        targetstepsoneyr = functions_pp.get_oneyr(RV.RV_ts)
        if type(self.lags[0]) == np.ndarray and targetstepsoneyr.size>1:
            raise ValueError('Precursor and Target do not align.\n'
                             'One aggregated value taken for months '
                             f'{self.lags[0]}, while target timeseries has '
                             f'multiple timesteps per year:\n{targetstepsoneyr}')
        yrs_precur_arr = np.unique(precur_arr.time.dt.year)
        if np.unique(dates.year).size != yrs_precur_arr.size:
            raise ValueError('Numer of years between precursor and Target '
                             'not match. Check if precursor period is crossyr, '
                             'while target period is not. '
                             'Mannually ensure start_end_year is aligned.')

        oneyr = functions_pp.get_oneyr(dates)
        if oneyr.size == 1: # single val per year precursor
            self._tfreq = 365
        else:
            self._tfreq = (oneyr[1] - oneyr[0]).days

        n_spl = df_splits.index.levels[0].size
        # make new xarray to store results
        xrcorr = precur_arr.isel(time=0).drop('time').copy()
        orig_mask = np.isnan(precur_arr[1])
        if 'lag' not in xrcorr.dims:
            # add lags
            list_xr = [xrcorr.expand_dims('lag', axis=0) for i in range(n_lags)]
            xrcorr = xr.concat(list_xr, dim = 'lag')
            xrcorr['lag'] = ('lag', self.lag_coordname)
        # add train test split
        list_xr = [xrcorr.expand_dims('split', axis=0) for i in range(n_spl)]
        xrcorr = xr.concat(list_xr, dim = 'split')
        xrcorr['split'] = ('split', range(n_spl))
        xrpvals = xrcorr.copy()


        def MI_single_split(RV_ts, precur_train, s, alpha=.05, FDR_control=True):

            lat = precur_train.latitude.values
            lon = precur_train.longitude.values

            z = np.zeros((lat.size*lon.size,len(lags) ) )
            Corr_Coeff = np.ma.array(z, mask=z)
            pvals = np.ones((lat.size*lon.size,len(lags) ) )

            dates_RV = RV_ts.index
            for i, lag in enumerate(lags):
                if type(lag) is np.int16 and self.lag_as_gap==False:
                    # dates_lag = functions_pp.func_dates_min_lag(dates_RV, self._tfreq*lag)[1]
                    m = apply_shift_lag(self.df_splits.loc[s], lag)
                    dates_lag = m[np.logical_and(m['TrainIsTrue'], m['x_fit'])].index
                    corr_val, pval = self.func(precur_train.sel(time=dates_lag),
                                               RV_ts.values.squeeze(),
                                               **self.kwrgs_func)
                elif type(lag) == np.int16 and self.lag_as_gap==True:
                    # if only shift tfreq, then gap=0
                    datesdaily = RV.aggr_to_daily_dates(dates_RV, tfreq=self._tfreq)
                    dates_lag = functions_pp.func_dates_min_lag(datesdaily,
                                                                self._tfreq+lag)[1]

                    tmb = functions_pp.time_mean_bins
                    corr_val, pval = self.func(tmb(precur_train.sel(time=dates_lag),
                                                           to_freq=self._tfreq)[0],
                                               RV_ts.values.squeeze(),
                                               **self.kwrgs_func)
                elif type(lag) == np.ndarray:
                    corr_val, pval = self.func(precur_train.sel(lag=i),
                                               RV_ts.values.squeeze(),
                                               **self.kwrgs_func)



                mask = np.ones(corr_val.size, dtype=bool)
                if FDR_control == True:
                    # test for Field significance and mask unsignificant values
                    # FDR control:
                    adjusted_pvalues = multicomp.multipletests(pval, method='fdr_bh')
                    ad_p = adjusted_pvalues[1]
                    pvals[:,i] = ad_p
                    mask[ad_p <= alpha] = False

                else:
                    pvals[:,i] = pval
                    mask[pval <= alpha] = False

                Corr_Coeff[:,i] = corr_val[:]
                Corr_Coeff[:,i].mask = mask

            Corr_Coeff = np.ma.array(data = Corr_Coeff[:,:], mask = Corr_Coeff.mask[:,:])
            Corr_Coeff = Corr_Coeff.reshape(lat.size,lon.size,len(lags)).swapaxes(2,1).swapaxes(1,0)
            pvals = pvals.reshape(lat.size,lon.size,len(lags)).swapaxes(2,1).swapaxes(1,0)
            return Corr_Coeff, pvals

        print('\n{} - calculating correlation maps'.format(precur_arr.name))
        np_data = np.zeros_like(xrcorr.values)
        np_mask = np.zeros_like(xrcorr.values)
        np_pvals = np.zeros_like(xrcorr.values)
        RV_mask = df_splits.loc[0]['RV_mask']
        for s in xrcorr.split.values:
            progress = int(100 * (s+1) / n_spl)
            # =============================================================================
            # Split train test methods ['random'k'fold', 'leave_'k'_out', ', 'no_train_test_split']
            # =============================================================================
            RV_train_mask = np.logical_and(RV_mask, df_splits.loc[s]['TrainIsTrue'])
            RV_ts = RV.fullts[RV_train_mask.values]
            TrainIsTrue = df_splits.loc[s]['TrainIsTrue'].values
            if self.lag_as_gap: # no clue why selecting all datapoints, changed 26-01-2021
                train_dates = df_splits.loc[s]['TrainIsTrue'][TrainIsTrue].index
                precur_train = precur_arr.sel(time=train_dates)
            else:
                precur_train = precur_arr[TrainIsTrue] # only train data

            dates_RV = RV_ts.index
            n = dates_RV.size ; r = int(100*n/RV.dates_RV.size )
            print(f"\rProgress traintest set {progress}%, trainsize=({n}dp, {r}%)", end="")

            ma_data, pvals = MI_single_split(RV_ts, precur_train.copy(), s,
                                             alpha=self.alpha,
                                             FDR_control=self.FDR_control)

            np_data[s] = ma_data.data
            np_mask[s] = ma_data.mask
            np_pvals[s]= pvals
        print("\n")
        xrcorr.values = np_data
        xrpvals.values = np_pvals
        mask = (('split', 'lag', 'latitude', 'longitude'), np_mask )
        xrcorr.coords['mask'] = mask
        # fill nans with mask = True
        xrcorr['mask'] = xrcorr['mask'].where(orig_mask==False, other=orig_mask).drop('time')
        #%%
        return xrcorr, xrpvals

    # def check_exception_time_mean_period(df_splits, precur_train)

    def adjust_significance_threshold(self, alpha):
        self.alpha = alpha
        self.corr_xr.mask.values = (self.pval_xr > self.alpha).values

    def get_prec_ts(self, precur_aggr=None, kwrgs_load=None): #, outdic_precur #TODO
        # tsCorr is total time series (.shape[0]) and .shape[1] are the correlated regions
        # stacked on top of each other (from lag_min to lag_max)

        n_tot_regs = 0
        splits = self.corr_xr.split
        if hasattr(self, 'prec_labels') == False:
            print(f'{self.name} is not clustered yet')
        else:
            if np.isnan(self.prec_labels.values).all():
                self.ts_corr = np.array(splits.size*[[]])
            else:
                if self.calc_ts == 'region mean':
                    self.ts_corr = find_precursors.spatial_mean_regions(self,
                                                  precur_aggr=precur_aggr,
                                                  kwrgs_load=kwrgs_load)
                elif self.calc_ts == 'pattern cov':
                    self.ts_corr = loop_get_spatcov(self,
                                                    precur_aggr=precur_aggr,
                                                    kwrgs_load=kwrgs_load)

                n_tot_regs += max([self.ts_corr[s].shape[1] for s in range(splits.size)])
        return

    def store_netcdf(self, path: str=None, f_name: str=None):
        assert hasattr(self, 'corr_xr'), 'No MI map calculated'
        if path is None:
            path = functions_pp.get_download_path()
        hash_str  = uuid.uuid4().hex[:6]
        f_name = '{}_a{}'.format(self._name, self.alpha)
        self.corr_xr.attrs['alpha'] = self.alpha
        self.corr_xr.attrs['FDR_control'] = int(self.FDR_control)
        self.corr_xr['lag'] = ('lag', range(self.lags.shape[0]))
        if hasattr(self, 'prec_labels'):
            self.prec_labels['lag'] = self.corr_xr['lag'] # must be same
            self.prec_labels.attrs['distance_eps'] = self.distance_eps
            self.prec_labels.attrs['min_area_in_degrees2'] = self.min_area_in_degrees2
            self.prec_labels.attrs['group_lag'] = int(self.group_lag)
            self.prec_labels.attrs['group_split'] = int(self.group_split)
            f_name += '_{}_{}'.format(self.distance_eps,
                                      self.min_area_in_degrees2)
            ds = xr.Dataset({'corr_xr':self.corr_xr,
                             'prec_labels':self.prec_labels,
                             'precur_arr':self.precur_arr.drop('mask')})
        else:
            ds = xr.Dataset({'corr_xr':self.corr_xr,
                             'precur_arr':self.precur_arr.drop('mask')})
        f_name += f'_{hash_str}'
        filepath = os.path.join(path, f_name+ '.nc')
        ds.to_netcdf(filepath)
        print(f'Dataset stored with hash: {hash_str}')

    def load_files(self, path_hashfile=str, hash_str=str):
        #%%
        for root, dirs, files in os.walk(path_hashfile):
            for file in files:
                if re.findall(f'{hash_str}', file):
                    print(file)
                    f_name = file
        filepath = os.path.join(path_hashfile, f_name)
        self.ds = core_pp.import_ds_lazy(filepath)
        self.corr_xr = self.ds['corr_xr']
        self.alpha = self.corr_xr.attrs['alpha']
        self.FDR_control = bool(self.corr_xr.attrs['FDR_control'])
        self.precur_arr = self.ds['precur_arr']
        if 'prec_labels' in self.ds.variables.keys():
            self.prec_labels = self.ds['prec_labels']
            self.distance_eps = self.prec_labels.attrs['distance_eps']
            self.min_area_in_degrees2 = self.prec_labels.attrs['min_area_in_degrees2']
            self.group_lag = bool(self.prec_labels.attrs['group_lag'])
            self.group_split = bool(self.prec_labels.attrs['group_split'])


        #%%
def check_NaNs(field, ts):
    '''
    Return shortened timeseries of both field and ts if a few NaNs are detected
    at boundary due to large lag. At boundary time-axis, large lags
    often result in NaNs due to missing data.
    Removing timesteps from timeseries if
    1. Entire field is filled with NaNs
    2. Number of timesteps are less than a single year
       of datapoints.
    '''
    t = functions_pp.get_oneyr(field).size # threshold NaNs allowed.
    field = np.reshape(field.values, (field.shape[0],-1))
    # for i in range(t):
    i = 0 ; # check NaNs in first year
    if bool(np.isnan(field[i]).all()):
        i+=1
        while bool(np.isnan(field[i]).all()):
            i+=1
            if i > t:
                raise ValueError('More NaNs detected then # of datapoints in '
                                 'single year')
    j = -1 ; # check NaNs in first year
    if bool(np.isnan(field[j]).all()):
        j-=1
        while bool(np.isnan(field[j]).all()):
            j-=1
            if j < t:
                raise ValueError('More NaNs detected then # of datapoints in '
                                 'single year')
    else:
        j = field.shape[0]
    return field[i:j], ts[i:j]


def corr_map(field, ts):
    """
    This function calculates the correlation coefficent r and
    the pvalue p for each grid-point of field vs response-variable ts
    If more then a single year of NaNs is detected, a NaN will
    be returned, otherwise corr is calculated over non-NaN values.

    """
    # if more then one year is filled with NaNs -> no corr value calculated.
    field, ts = check_NaNs(field, ts)
    x = np.ma.zeros(field.shape[1])
    corr_vals = np.array(x)
    pvals = np.array(x)

    fieldnans = np.array([np.isnan(field[:,i]).any() for i in range(x.size)])
    nonans_gc = np.arange(0, fieldnans.size)[fieldnans==False]

    for i in nonans_gc:
        corr_vals[i], pvals[i] = scipy.stats.pearsonr(ts,field[:,i])
    # restore original nans
    corr_vals[fieldnans] = np.nan
    # correlation map and pvalue at each grid-point:

    return corr_vals, pvals

def parcorr_map_time(field, ts, lag=1, target=True, precursor=True):

    # if more then one year is filled with NaNs -> no corr value calculated.
    field, ts = check_NaNs(field, ts)
    field = np.reshape(field.values, (field.shape[0],-1))
    x = np.ma.zeros(field.shape[1])
    corr_vals = np.array(x)
    pvals = np.array(x)

    fieldnans = np.array([np.isnan(field[:,i]).any() for i in range(x.size)])
    nonans_gc = np.arange(0, fieldnans.size)[fieldnans==False]
    if target:
        zy = np.expand_dims(ts[:-lag], axis=1)
    y = np.expand_dims(ts[lag:], axis=1)
    for i in nonans_gc:
        cond_ind_test = ParCorr()
        if precursor and target:
            z2 = np.expand_dims(field[:-lag, i], axis=1)
            z = np.concatenate((zy,z2), axis=1)
        elif precursor and target==False:
            z = np.expand_dims(field[:-lag, i], axis=1)
        elif precursor==False and target:
            z = zy
        field_i = np.expand_dims(field[lag:,i], axis=1)
        a, b = cond_ind_test.run_test_raw(y, field_i, z)
        corr_vals[i] = a
        pvals[i] = b
    # restore original nans
    corr_vals[fieldnans] = np.nan
    return corr_vals, pvals

def parcorr_z(field, ts, z=pd.DataFrame):
    # if more then one year is filled with NaNs -> no corr value calculated.
    field, ts = check_NaNs(field, ts)
    dates = pd.to_datetime(field.time.values)
    field = np.reshape(field.values, (field.shape[0],-1))
    x = np.ma.zeros(field.shape[1])
    corr_vals = np.array(x)
    pvals = np.array(x)
    fieldnans = np.array([np.isnan(field[:,i]).any() for i in range(x.size)])
    nonans_gc = np.arange(0, fieldnans.size)[fieldnans==False]

    ts = np.expand_dims(ts[:], axis=1) # adjust to shape (samples, dimension)
    z = np.expand_dims(z.loc[dates].values.squeeze(), axis=1)
    for i in nonans_gc:
        cond_ind_test = ParCorr()
        x = np.expand_dims(field[:,i], axis=1)
        a, b = cond_ind_test.run_test_raw(x, ts, z)
        corr_vals[i] = a
        pvals[i] = b
    # restore original nans
    corr_vals[fieldnans] = np.nan
    return corr_vals, pvals

def loop_get_spatcov(precur, precur_aggr, kwrgs_load):

    name            = precur.name
    corr_xr         = precur.corr_xr
    prec_labels     = precur.prec_labels
    df_splits       = precur.df_splits
    splits          = df_splits.index.levels[0]
    lags            = precur.corr_xr.lag.values
    use_sign_pattern= precur.use_sign_pattern
    tfreq           = precur.tfreq

    if precur_aggr is None and (tfreq != 365 and len(lags)==1):
        # use precursor array with temporal aggregation that was used to create
        # correlation map. When tfreq=365 and lag>1, reaggregate months precur_arr
        precur_arr = precur.precur_arr
    else:
        # =============================================================================
        # Unpack kwrgs for loading
        # =============================================================================
        kwrgs = {'selbox':precur.selbox, 'dailytomonths':precur.dailytomonths}
        for key, value in kwrgs_load.items():
            if type(value) is list and name in value[1].keys():
                kwrgs[key] = value[1][name]
            elif type(value) is list and name not in value[1].keys():
                kwrgs[key] = value[0] # plugging in default value
            elif hasattr(precur, key):
                # Overwrite RGCPD parameters with MI specific parameters
                kwrgs[key] = precur.__dict__[key]
            else:
                kwrgs[key] = value
        if precur_aggr is None:
            precur_aggr = tfreq
        kwrgs['tfreq'] = precur_aggr

        if tfreq == 365:
            # create seperate xarray with monthly means, of which grouped
            # means will be calculated defined by lag, lag=[1,2,3]=JFM mean
            precur_months = functions_pp.import_ds_timemeanbins(precur.filepath,
                                                         **kwrgs)
        else:
            print('aggregating precursors to {} days '.format(kwrgs['tfreq']) + \
                  'closed on right {}'.format(kwrgs['closed_on_date']))

            precur_arr = functions_pp.import_ds_timemeanbins(precur.filepath,
                                                         **kwrgs)

    if precur_arr.shape[-2:] != corr_xr.shape[-2:]:
        print('shape loaded precur_arr != corr map, matching coords')
        corr_xr, prec_labels = functions_pp.match_coords_xarrays(precur_arr,
                                          *[corr_xr, prec_labels])

    ts_sp = np.zeros( (splits.size), dtype=object)
    for s in splits:
        ts_list = np.zeros( (lags.size), dtype=list )
        track_names = []
        for il,lag in enumerate(lags):

            # if lag represents months to aggregate:
            if type(lag) is np.str_: # aggr. over months
                months = [int(l) for l in lag.split('.')[:-1]]
                precur_arr = precur_months.sel(time=
                                            np.in1d(precur_months['time.month'],
                                            months))
                precur_arr = precur_arr.groupby('time.year',
                                            restore_coord_dims=True).mean()
                d = pd.to_datetime([f'{Y}-01-01' for Y in precur_arr.year.values])
                precur_arr = precur_arr.rename({'year':'time'}).assign_coords(
                                                {'time':d})

            corr_vals = corr_xr.sel(split=s).isel(lag=il)
            mask = prec_labels.sel(split=s).isel(lag=il)
            pattern = corr_vals.where(~np.isnan(mask))
            if use_sign_pattern == True:
                pattern = np.sign(pattern)
            if np.isnan(pattern.values).all():
                # no regions of this variable and split
                nants = np.zeros( (precur_arr.time.size, 1) )
                nants[:] = np.nan
                ts_list[il] = nants
                pass
            else:
                # if normalize == True:
                #     spatcov_full = calc_spatcov(full_timeserie, pattern)
                #     mean = spatcov_full.sel(time=dates_train).mean(dim='time')
                #     std = spatcov_full.sel(time=dates_train).std(dim='time')
                #     spatcov_test = ((spatcov_full - mean) / std)
                # elif normalize == False:
                xrts = find_precursors.calc_spatcov(precur_arr, pattern)
                ts_list[il] = xrts.values[:,None]
            track_names.append(f'{lag}..0..{precur.name}' + '_sp')

        # concatenate timeseries all of lags
        tsCorr = np.concatenate(tuple(ts_list), axis = 1)

        dates = pd.to_datetime(precur_arr.time.values)
        ts_sp[s] = pd.DataFrame(tsCorr,
                                index=dates,
                                columns=track_names)
    # df_sp = pd.concat(list(ts_sp), keys=range(splits.size))
    return ts_sp

