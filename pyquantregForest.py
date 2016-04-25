# -*- coding: utf-8 -*-
from sklearn.ensemble import RandomForestRegressor
from sklearn.ensemble.forest import BaseForest, ForestRegressor
import numpy as np
from scipy.optimize import fmin_cobyla, fmin_slsqp, basinhopping
from pathos.multiprocessing import ProcessingPool
from pandas import DataFrame, Series
import pylab as plt
#from cma import CMAEvolutionStrategy

class QuantileForest(RandomForestRegressor):
    """Quantile Regresion Random Forest.
      This class can build random forest using Scikit-Learn and compute
      conditional quantiles.

      Parameters
      ----------
      inputSample : array
        Input samples used in data

      outputSample : array
        Output samples used in data

      n_estimators : int, optional (default=50)
        The number of trees in the forest.

      max_leaf_nodes : int or None, optional (default=max(10, len(outputSample)/100))
        Grow trees with max_leaf_nodes in best-first fashion. Best nodes are
        defined as relative reduction in impurity. If None then unlimited
        number of leaf nodes. If not None then max_depth will be ignored.
        Note: this parameter is tree-specific.

      n_jobs : int, optional (default=4)
        The number of jobs to run in parallel for both fit and predict. If -1,
        then the number of jobs is set to the number of cores.

      numPoints : int, optional (default=0)
        The size of the vector used to determines the quantile. If 0, the
        vector use is the outputSample.

      outputSample : string, optional (default="Cobyla")
        Name of the Optimisation method to find the alpha-quantile (if the
        option is chosen in the computeQuantile method). Only "Cobyla" and
        "SQP" are available.

      random_state : int, RandomState instance or None, optional (default=None)
        If int, random_state is the seed used by the random number generator;
        If RandomState instance, random_state is the random number generator;
        If None, the random number generator is the RandomState instance used
        by np.random.
    """


    def fit(self, X, y):
        """

        """
        # We transform X as a np array for use convenience
        X = np.asarray(X)

        # It's a vector
        if X.shape[0] == X.size:
            self._n_sample = X.shape[0]
            self._input_dim = 1
        else:
            self._n_sample, self._input_dim = X.shape

        # The bootstrap is mandatory for the method. Since update 
        # 1.16 of Sklearn, the indices of each element are not 
        # availables. TODO: find a way to get OOB indices.
        self.bootstrap = True

        # Fit the forest
        RandomForestRegressor.fit(self, X, y)

        # Save the data. Necessary to compute the quantiles.
        self._input_sample = DataFrame(X)
        self._output_sample = Series(y)

        # The resulting node of each elements of the sample
        self._sample_nodes = DataFrame(self.apply(X))  

        return self

    def _check_input(self, X):
        """

        """
        n = X.shape[0]  # Number of sample
        try:  # Works if X is an array
            d = X.shape[1]  # Dimension of the array
            if d != self._input_dim:  # If the dimension is not correct
                if n == self._input_dim:  # There is one sample of d dimension
                    d = n
                    n = 1
                else:  # Error
                    raise ValueError("X dimension is different from forest \
                    dimension : %d (X) != %d (forest)" % (d, self._input_dim))
        except:  # Its a vector
            d = 1
            if d != self._input_dim:  # If the dimension is not correct
                if n == self._input_dim:  # There is one sample of d dimension
                    d = n
                    n = 1
                else:  # Error
                    raise ValueError("X dimension is different from forest \
                    dimension : %d (X) != %d (forest)" % (d, self._input_dim))

        if (n > 1) & (d == 1):
            X.resize(n, 1)

        return X, n

    def computeQuantile(self, X, alpha, do_optim=True, verbose=False,
                        doSaveCDF=False, iTree=-1, opt_method="Cobyla"):
        """
        Compute the conditional alpha-quantile.
        """
        if type(X) in [int, float]:
            alpha = [alpha]
        if type(X) in [int, float]:
            X = [X]

        # Converting to array for convenience
        alpha = np.asarray(alpha)
        X = np.asarray(X)

        # Number of quantiles to compute
        X, n_quantiles = self._check_input(X)
        n_alphas = alpha.size  # Number of probabilities

        # Matrix of computed quantiles
        quantiles = np.zeros((n_quantiles, n_alphas))

        if doSaveCDF or not do_optim:
            self.setPrecisionOfCDF(self._n_points)
        if doSaveCDF:
            self._CDF = np.empty((self._yCDF.size, n_quantiles))

        # Nodes of the regressor in all the trees
        # Shape : (numTree * numRegressor)
        if iTree < 0:
            if n_quantiles == 1 and self._input_dim == 1:
                X_nodes = self.apply(X[0]).transpose()
            else:
                X_nodes = self.apply(X).transpose()
            sample_node = self._sample_nodes.values
        else:
            tree = self.estimators_[iTree].tree_
            X_nodes = tree.apply(X.astype(np.float32))
            X_nodes.resize((1, n_quantiles))
            sample_node = self._nodesOfSamples.values[:, iTree]

        # For each quantiles to compute
        for k in range(n_quantiles):
            # Set to 1 only the samples in the same nodes the regressor,
            # Shape : Matrix (numSample * numTree)
            tmp = (sample_node == X_nodes[:, k])

            # Number of samples in nodes
            n_samples_nodes = tmp.sum(axis=0)

            # The proportion in each node
            # Shape : Matrix (numSample * numTree)
            weight = tmp.astype(float) / n_samples_nodes

            # The weight of each sample in the trees
            # Shape : Vector (numSample * )
            if iTree < 0:
                weight = weight.mean(axis=1)
            else:
                weight = weight

            # Compute the quantile by minimising the pinball function
            if do_optim:
                # The starting point is the percentile
                # of the non-zero weights.
                y0 = np.percentile(self._output_sample[
                                   weight != 0], alpha * 100.)

                for i, alphai in enumerate(alpha):
                    if opt_method == "Cobyla":
                        quantiles[k, i] = fmin_cobyla(self._optFunc,
                                                      y0[i],
                                                      [self._ieqFunc],
                                                      args=(weight, alphai),
                                                      disp=verbose)

                    elif opt_method == "SQP":
                        epsilon = 1.E-1 * abs(y0[i])
                        quantiles[k, i] = fmin_slsqp(self._optFunc,
                                                     y0[i],
                                                     f_ieqcons=self._ieqFunc,
                                                     args=(weight, alphai),
                                                     disp=verbose,
                                                     epsilon=epsilon)

                    else:
                        raise ValueError("Unknow optimisation method %s" %
                                         opt_method)
            else:
                CDF = self._infYY.dot(weight).ravel()  # Compute the CDF
                quantiles[k, :] = [self._yCDF.values[CDF >= alphai][0]
                                   for alphai in alpha]
                if doSaveCDF:
                    self._CDF[:, k] = CDF

        if n_quantiles == 1 and n_alphas == 1:
            return quantiles[0][0]
        elif n_quantiles == 1 or n_alphas == 1:
            return quantiles.ravel()
        else:
            return quantiles

    def _optFunc(self, yi, w, alpha):
        """

        """
        alphai = w[self._output_sample.values <= yi].sum()        
        return check_function(self._output_sample.values[w != 0], yi, alpha).sum()
        #return abs(alphai - alpha)**2

    def _ieqFunc(self, yi, w, alpha):
        """

        """
        alphai = w[self._output_sample.values <= yi].sum()
        return alphai - alpha
    
# ==============================================================================
# Setters
# ==============================================================================
    def setPrecisionOfCDF(self, n_points):
        """
        If the value is set at 0, we will take the quantile from the output
        sample. Else we can create new sample to find the quantile
        """
        if n_points == 0:  # We use the outputSample as precision vector
            self._yCDF = self._outputSample.sort(inplace=False)
        else:  # We create a vector
            yymin = self._outputSample.min()
            yymax = self._outputSample.max()
            self._yCDF = Series(np.linspace(yymin, yymax, n_points))

        # Matrix of output samples inferior to a quantile value
        outMatrix = self._outputSample.reshape(self._numSample, 1)
        cdfMatrix = self._yCDF.reshape(self._yCDF.size, 1).T
        self._infYY = DataFrame(outMatrix <= cdfMatrix).T

    def _computeImportanceOfTree(self, alpha, i):
        """

        """
        oob = self._oobID[i]
        X_oob = self._inputSample.values[oob, :]
        Yobs_oob = self._outputSample.values[oob]
        Yest_oob = self.computeQuantile(X_oob, alpha, iTree=i)
        baseError = (check_function(Yobs_oob, Yest_oob, alpha)).mean()

        permError = np.empty(self._input_dim)
        for j in range(self._input_dim):
            X_oob_perm = np.array(X_oob)
            np.random.shuffle(X_oob_perm[:, j])
            Yest_oob_perm = self.computeQuantile(X_oob_perm, alpha, iTree=i)
            permError[j] = check_function(Yobs_oob, Yest_oob_perm, alpha)\
                .mean()

        return (permError - baseError)

    def compute_importance(self, alpha):
        """

        """
        pool = ProcessingPool(self._numJobs)
        errors = pool.map(self._computeImportanceOfTree,
                          [alpha] * self._numTree, range(self._numTree))
        return np.array(errors).mean(axis=0)


def check_function(y, yi, alpha):
    """

    """
    u = y - yi
    return u * (alpha - (u < 0.) * 1.)

if __name__ == "__main__":
    """
    The main execution is just an example of the Quantile Regression Forest 
    applied on a sinusoidal function with Gaussian noise.
    """

    def sin_func(X):
        X = np.asarray(X)
        return 3*X
    
    np.random.seed(0)
    dim = 1
    n_sample = 200
    xmin, xmax = 0., 5.
    X = np.linspace(xmin, xmax, n_sample).reshape((n_sample, 1))
    y = sin_func(X).ravel() + np.random.randn(n_sample)
    
    quantForest = QuantileForest().fit(X, y)

    n_quantiles = 10
    alpha = 0.9
    x = np.linspace(xmin, xmax, n_quantiles)
    x = 3.
    quantiles = quantForest.computeQuantile(x, alpha)
    print quantiles

    if dim == 1:
        plt.ion()
        fig, ax = plt.subplots()
        ax.plot(X, y, '.k')
        ax.plot(x, quantiles, 'ob')
        fig.tight_layout()
        plt.show()