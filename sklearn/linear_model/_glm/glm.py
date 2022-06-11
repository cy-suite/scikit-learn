"""
Generalized Linear Models with Exponential Dispersion Family
"""

# Author: Christian Lorentzen <lorentzen.ch@gmail.com>
# some parts and tricks stolen from other sklearn files.
# License: BSD 3 clause

from abc import ABC, abstractmethod
import numbers
import warnings

import numpy as np
import scipy.linalg
import scipy.sparse.linalg
import scipy.optimize
import scipy.sparse

from ..._loss.glm_distribution import TweedieDistribution
from ..._loss.loss import (
    HalfGammaLoss,
    HalfPoissonLoss,
    HalfSquaredError,
    HalfTweedieLoss,
    HalfTweedieLossIdentity,
)
from ...base import BaseEstimator, RegressorMixin
from ...exceptions import ConvergenceWarning
from ...utils import check_scalar, check_array, deprecated
from ...utils._openmp_helpers import _openmp_effective_n_threads
from ...utils.optimize import _check_optimize_result
from ...utils.validation import check_is_fitted, _check_sample_weight
from .._linear_loss import LinearModelLoss


class NewtonSolver(ABC):
    """Newton solver for GLMs.

    This class implements Newton/2nd-order optimization for GLMs. Each Newton iteration
    aims at finding the Newton step which is done by the inner solver. With hessian H,
    gradient g and coefficients coef, one step solves

        H @ coef_newton = -g

    For our GLM / LinearModelLoss, we have gradient g and hessian H:

        g = X.T @ loss.gradient + l2_reg_strength * coef
        H = X.T @ diag(loss.hessian) @ X + l2_reg_strength * identity

    Backtracking line seach updates coef = coef_old + t * coef_newton for some t in
    (0, 1].

    This is a base class, actual implementations (child classes) may deviate from the
    above pattern and use structure specific tricks.

    Usage pattern:
        - initialize solver: sol = NewtonSolver(...)
        - solve the problem: sol.solve(X, y, sample_weight)

    References
    ----------
    - Jorge Nocedal, Stephen J. Wright. (2006) "Numerical Optimization"
      2nd edition
      https://doi.org/10.1007/978-0-387-40065-5

    - Stephen P. Boyd, Lieven Vandenberghe. (2004) "Convex Optimization."
      Cambridge University Press, 2004.
      https://web.stanford.edu/~boyd/cvxbook/bv_cvxbook.pdf

    Parameters
    ----------
    coef : ndarray of shape (n_dof,), (n_classes, n_dof) or (n_classes * n_dof,), \
        default=None
        Start coefficients of a linear model.
        If shape (n_classes * n_dof,), the classes of one feature are contiguous,
        i.e. one reconstructs the 2d-array via
        coef.reshape((n_classes, -1), order="F").
        If None, they are initialized with zero.

    linear_loss : LinearModelLoss
        The loss to be minimized.

    l2_reg_strength : float, default=0.0
            L2 regularization strength

    tol : float, default=1e-4
        The optimization problem is solved when each of the following condition is
        fulfilled:
        1. maximum |gradient| <= tol
        2. Newton decrement d: 1/2 * d^2 <= tol

    max_iter : int, default=100
        Maximum number of Newton steps allowed.

    n_threads : int, default=1
        Number of OpenMP threads to use for the computation of the hessian and gradient
        of the loss function.
    """

    def __init__(
        self,
        *,
        coef=None,
        linear_loss=LinearModelLoss(base_loss=HalfSquaredError, fit_intercept=True),
        l2_reg_strength=0.0,
        tol=1e-4,
        max_iter=100,
        n_threads=1,
        verbose=0,
    ):
        self.coef = coef
        self.linear_loss = linear_loss
        self.l2_reg_strength = l2_reg_strength
        self.tol = tol
        self.max_iter = max_iter
        self.n_threads = n_threads
        self.verbose = verbose

    def setup(self, X, y, sample_weight):
        """Precomputations

        If None, initializes:
            - self.coef
        Sets:
            - self.raw_prediction
            - self.loss_value
        """
        if self.coef is None:
            self.coef = self.linear_loss.init_zero_coef(X)
            self.raw_prediction = np.zeros_like(y)
        else:
            _, _, self.raw_prediction = self.linear_loss.weight_intercept_raw(
                self.coef, X
            )
        self.loss_value = self.linear_loss.loss(
            coef=self.coef,
            X=X,
            y=y,
            sample_weight=sample_weight,
            l2_reg_strength=self.l2_reg_strength,
            n_threads=self.n_threads,
            raw_prediction=self.raw_prediction,
        )

    @abstractmethod
    def update_gradient_hessian(self, X, y, sample_weight):
        """Update gradient and hessian."""

    @abstractmethod
    def inner_solve(self, X, y, sample_weight):
        """Compute Newton step.

        Sets self.coef_newton.
        """

    def line_search(self, X, y, sample_weight):
        """Backtracking line search.

        Sets:
            - self.coef_old
            - self.coef
            - self.loss_value_old
            - self.loss_value
            - self.gradient_old
            - self.gradient
            - self.raw_prediction
        """
        # line search parameters
        beta, sigma = 0.5, 0.00048828125  # 1/2, 1/2**11
        eps = 16 * np.finfo(self.loss_value.dtype).eps
        t = 1  # step size

        armijo_term = sigma * self.gradient @ self.coef_newton
        _, _, raw_prediction_newton = self.linear_loss.weight_intercept_raw(
            self.coef_newton, X
        )

        self.coef_old = self.coef
        self.loss_value_old = self.loss_value
        self.gradient_old = self.gradient

        # np.sum(np.abs(self.gradient_old))
        sum_abs_grad_old = -1
        sum_abs_grad_previous = -1  # Used to track sum|gradients| of i-1
        has_improved_sum_abs_grad_previous = False

        is_verbose = self.verbose >= 2
        if is_verbose:
            print("  Backtracking Line Search")
            print(f"    eps=10 * finfo.eps={eps}")

        for i in range(21):  # until and including t = beta**20 ~ 1e-6
            self.coef = self.coef_old + t * self.coef_newton
            raw = self.raw_prediction + t * raw_prediction_newton
            self.loss_value, self.gradient = self.linear_loss.loss_gradient(
                coef=self.coef,
                X=X,
                y=y,
                sample_weight=sample_weight,
                l2_reg_strength=self.l2_reg_strength,
                n_threads=self.n_threads,
                raw_prediction=raw,
            )
            # Note: If coef_newton is too large, loss_gradient may produce inf values,
            # potentially accompanied by a RuntimeWarning.
            # This case will be captured by the Armijo condition.

            # 1. Check Armijo / sufficient decrease condition.
            # The smaller (more negative) the better.
            loss_improvement = self.loss_value - self.loss_value_old
            check = loss_improvement <= t * armijo_term
            if is_verbose:
                print(
                    f"    line search iteration={i+1}, step size={t}\n"
                    f"      check loss improvement <= armijo term: {loss_improvement} "
                    f"<= {t * armijo_term} {check}"
                )
            if check:
                break
            # 2. Deal with relative loss differences around machine precision.
            tiny_loss = np.abs(self.loss_value_old * eps)
            check = np.abs(loss_improvement) <= tiny_loss
            if is_verbose:
                print(
                    "      check loss |improvement| <= eps * |loss_old|:"
                    f" {np.abs(loss_improvement)} <= {tiny_loss} {check}"
                )
            if check:
                if sum_abs_grad_old < 0:
                    sum_abs_grad_old = scipy.linalg.norm(self.gradient_old, ord=1)
                # 2.1 Check sum of absolute gradients as alternative condition.
                sum_abs_grad = scipy.linalg.norm(self.gradient, ord=1)
                check = sum_abs_grad < sum_abs_grad_old
                if is_verbose:
                    print(
                        "      check sum(|gradient|) <= sum(|gradient_old|): "
                        f"{sum_abs_grad} <= {sum_abs_grad_old} {check}"
                    )
                if check:
                    break
                # 2.2 Deal with relative gradient differences around machine precision.
                tiny_grad = sum_abs_grad_old * eps
                abs_grad_improvement = np.abs(sum_abs_grad - sum_abs_grad_old)
                check = abs_grad_improvement <= tiny_grad
                if is_verbose:
                    print(
                        "      check |sum(|gradient|) - sum(|gradient_old|)| <= eps * "
                        "sum(|gradient_old|):"
                        f" {abs_grad_improvement} <= {tiny_grad} {check}"
                    )
                if check:
                    break
                # 2.3 This is really the last resort.
                # Check that sum(|gradient_{i-1}|) < sum(|gradient_{i-2}|)
                #            = has_improved_sum_abs_grad_previous
                # If now sum(|gradient_{i}|) >= sum(|gradient_{i-1}|), this iteration
                # made things worse and we should have stopped at i-1.
                check = (
                    has_improved_sum_abs_grad_previous
                    and sum_abs_grad >= sum_abs_grad_previous
                )
                if is_verbose:
                    print(
                        "      check if previously "
                        f"sum(|gradient_{i-1}|) < sum(|gradient_{i-2}|) but now "
                        f"sum(|gradient_{i}|) >= sum(|gradient_{i-1}|) {check}"
                    )
                if check:
                    t /= beta  # we go back to i-1
                    self.coef = self.coef_old + t * self.coef_newton
                    raw = self.raw_prediction + t * raw_prediction_newton
                    self.loss_value, self.gradient = self.linear_loss.loss_gradient(
                        coef=self.coef,
                        X=X,
                        y=y,
                        sample_weight=sample_weight,
                        l2_reg_strength=self.l2_reg_strength,
                        n_threads=self.n_threads,
                        raw_prediction=raw,
                    )
                    break
                # Calculate for the next iteration
                has_improved_sum_abs_grad_previous = (
                    sum_abs_grad < sum_abs_grad_previous
                )
                sum_abs_grad_previous = sum_abs_grad

            t *= beta
        else:
            warnings.warn(
                f"Line search of Newton solver {self.__class__.__name__} at iteration "
                "#{self.iteration} did no converge after 21 line search refinement "
                "iterations.",
                ConvergenceWarning,
            )

        self.raw_prediction = raw

    def compute_d2(self, X):
        """Compute square of Newton decrement."""
        return self.coef_newton @ self.hessian @ self.coef_newton

    def check_convergence(self, X, y, sample_weight):
        """Check for convergence."""
        if self.verbose:
            print("  Check Convergence")
        # Note: Checking maximum relative change of coefficient <= tol is a bad
        # convergence criterion because even a large step could have brought us close
        # to the true minimum.
        # coef_step = self.coef - self.coef_old
        # check = np.max(np.abs(coef_step) / np.maximum(1, np.abs(self.coef_old)))

        # 1. Criterion: maximum |gradient| <= tol
        #    The gradient was already updated in line_search()
        check = np.max(np.abs(self.gradient))
        if self.verbose:
            print(f"    1. max |gradient| {check} <= {self.tol}")
        if check > self.tol:
            return

        # 2. Criterion: For Newton decrement d, check 1/2 * d^2 <= tol
        #       d = sqrt(grad @ hessian^-1 @ grad)
        #         = sqrt(coef_newton @ hessian @ coef_newton)
        #    See Boyd, Vanderberghe (2009) "Convex Optimization" Chapter 9.5.1.
        d2 = self.compute_d2(X)
        if self.verbose:
            print(f"    2. Newton decrement {0.5 * d2} <= {self.tol}")
        if 0.5 * d2 > self.tol:
            return

        if self.verbose:
            loss_value = self.linear_loss.loss(
                coef=self.coef,
                X=X,
                y=y,
                sample_weight=sample_weight,
                l2_reg_strength=self.l2_reg_strength,
                n_threads=self.n_threads,
            )
            print(f"  Solver did converge at loss = {loss_value}.")
        self.converged = True

    def finalize(self, X, y, sample_weight):
        """Finalize the solvers results.

        Some solvers may need this, others not.
        """
        pass

    def solve(self, X, y, sample_weight):
        """Solve the optimization problem.

        Order of calls:
            self.setup()
            while iteration:
                self.update_gradient_hessian()
                self.inner_solve()
                self.line_search()
                self.check_convergence()
            self.finalize()
        """
        # setup usually:
        #   - initializes self.coef if needed
        #   - initializes and calculates self.raw_predictions, self.loss_value
        self.setup(X=X, y=y, sample_weight=sample_weight)

        self.iteration = 1
        self.converged = False
        self.stop = False

        while self.iteration <= self.max_iter and not self.converged:
            if self.verbose:
                print(f"Newton iter={self.iteration}")
            # 1. Update hessian and gradient
            self.update_gradient_hessian(X=X, y=y, sample_weight=sample_weight)

            # TODO:
            # if iteration == 1:
            # We might stop early, e.g. we already are close to the optimum,
            # usually detected by zero gradients at this stage.

            # 2. Inner solver
            #    Calculate Newton step/direction
            #    This usually sets self.coef_newton.
            #    It may set self.stop = True, e.g. for ill-conditioned systems.
            self.inner_solve(X=X, y=y, sample_weight=sample_weight)
            if self.stop:
                break

            # 3. Backtracking line search
            #    This usually sets self.coef_old, self.coef, self.loss_value_old
            #    self.loss_value, self.gradient_old, self.gradient,
            #    self.raw_prediction.
            self.line_search(X=X, y=y, sample_weight=sample_weight)

            # 4. Check convergence
            #    Sets self.converged.
            self.check_convergence(X=X, y=y, sample_weight=sample_weight)

            # 5. Next iteration
            self.iteration += 1

        if not self.converged:
            warnings.warn(
                "Newton solver did not converge after"
                f" {self.iteration - 1} iterations.",
                ConvergenceWarning,
            )

        self.iteration -= 1
        self.finalize(X=X, y=y, sample_weight=sample_weight)
        return self.coef


class BaseCholeskyNewtonSolver(NewtonSolver):
    """Cholesky based Newton solver.

    Inner solver for finding the Newton step H w_newton = -g uses Cholesky based linear
    solver.
    """

    def setup(self, X, y, sample_weight):
        super().setup(X=X, y=y, sample_weight=sample_weight)
        self.count_singular = 0

    def inner_solve(self, X, y, sample_weight):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", scipy.linalg.LinAlgWarning)
                self.coef_newton = scipy.linalg.solve(
                    self.hessian, -self.gradient, check_finite=False, assume_a="sym"
                )
            return
        except (np.linalg.LinAlgError, scipy.linalg.LinAlgWarning) as e:
            if self.count_singular == 0:
                # We only need to throw this warning once.
                warnings.warn(
                    f"The inner solver of {self.__class__.__name__} stumbled upon a"
                    " singular or very ill-conditioned hessian matrix at iteration "
                    " #{self.iteration}. It will now try a simple gradient step."
                    " Note that this warning is only raised once, the problem may, "
                    " however, occur in several or all iterations. Set verbose >= 1"
                    " to get more information.\n"
                    "Your options are to use another solver or to avoid such situation"
                    " in the first place. Possible  remedies are removing collinear"
                    " features of X or increasing the penalization strengths.\n"
                    "The original Linear Algebra message was:\n"
                    + str(e),
                    scipy.linalg.LinAlgWarning,
                )
            self.count_singular += 1
            # Possible causes:
            # 1. hess_pointwise is negative. But this is already taken care in
            #    LinearModelLoss such that min(hess_pointwise) >= 0.
            # 2. X is singular or ill-conditioned
            #    This might be the most probable cause.
            #
            # There are many possible ways to deal with this situation (most of
            # them adding, explicit or implicit, a matrix to the hessian to make it
            # positive definite), confer to Chapter 3.4 of Nocedal & Wright 2nd ed.
            # Instead, we resort to a simple gradient step, taking the diagonal part
            # of the hessian.
            if self.verbose:
                print(
                    "  The inner solver stumbled upon an singular or ill-conditioned "
                    "hessian matrix and resorts to a simple gradient step."
                )
            # We add 1e-3 to the diagonal hessian part to make in invertible and to
            # restrict coef_newton to at most ~1e3. The line search considerst step
            # sizes until 1e-6 * newton_step ~1e-3 * newton_step.
            # Deviding by self.iteration ensures (slow) convergence.
            eps = 1e-3 / self.iteration
            self.coef_newton = -self.gradient / (np.diag(self.hessian) + eps)
            # We have throw this above warning an just stop.
            # self.stop = True


class CholeskyNewtonSolver(BaseCholeskyNewtonSolver):
    """Cholesky based Newton solver.

    Inner solver for finding the Newton step H w_newton = -g uses Cholesky based linear
    solver.
    """

    def setup(self, X, y, sample_weight):
        super().setup(X=X, y=y, sample_weight=sample_weight)

        n_dof = X.shape[1]
        if self.linear_loss.fit_intercept:
            n_dof += 1
        self.gradient = np.empty_like(self.coef)
        self.hessian = np.empty_like(self.coef, shape=(n_dof, n_dof))

    def update_gradient_hessian(self, X, y, sample_weight):
        self.linear_loss.gradient_hessian(
            coef=self.coef,
            X=X,
            y=y,
            sample_weight=sample_weight,
            l2_reg_strength=self.l2_reg_strength,
            n_threads=self.n_threads,
            gradient_out=self.gradient,
            hessian_out=self.hessian,
            raw_prediction=self.raw_prediction,  # this was updated in line_search
        )


class QRCholeskyNewtonSolver(BaseCholeskyNewtonSolver):
    """QR and Cholesky based Newton solver.

    This is a good solver for n_features >> n_samples, see [1].

    This solver uses the structure of the problem, i.e. the fact that coef enters the
    loss function only as X @ coef and ||coef||_2, and starts with an economic QR
    decomposition of X':

        X' = QR with Q'Q = identity(k), k = min(n_samples, n_features)

    This is the same as an LQ decomposition of X. We introduce the new variable t as,
    see [1]:

        (coef, intercept) = (Q @ t, intercept)

    By using X @ coef = R' @ t and ||coef||_2 = ||t||_2, we can just replace X
    by R', solve for t instead of coef, and finally get coef = Q @ t.
    Note that t has less elements than coef if n_features > n_samples:
        len(t) = k = min(n_samples, n_features) <= n_features = len(coef).

    [1] Hastie, T.J., & Tibshirani, R. (2003). Expression Arrays and the p n Problem.
    https://web.stanford.edu/~hastie/Papers/pgtn.pdf
    """

    def setup(self, X, y, sample_weight):
        n_samples, n_features = X.shape
        # TODO: setting pivoting=True could improve stability
        # QR of X'
        self.Q, self.R = scipy.linalg.qr(X.T, mode="economic", pivoting=False)
        # use k = min(n_features, n_samples) instead of n_features
        k = self.R.T.shape[1]
        n_dof = k
        if self.linear_loss.fit_intercept:
            n_dof += 1
        # store original coef
        self.coef_original = self.coef
        # set self.coef = t (coef_original = Q @ t)
        self.coef = np.zeros_like(self.coef, shape=n_dof)
        if np.sum(np.abs(self.coef_original)) > 0:
            self.coef[:k] = self.Q.T @ self.coef_original[:n_features]
        self.gradient = np.empty_like(self.coef)
        self.hessian = np.empty_like(self.coef, shape=(n_dof, n_dof))

        super().setup(X=self.R.T, y=y, sample_weight=sample_weight)

    def update_gradient_hessian(self, X, y, sample_weight):
        # Use R' instead of X
        self.linear_loss.gradient_hessian(
            coef=self.coef,
            X=self.R.T,
            y=y,
            sample_weight=sample_weight,
            l2_reg_strength=self.l2_reg_strength,
            n_threads=self.n_threads,
            gradient_out=self.gradient,
            hessian_out=self.hessian,
            raw_prediction=self.raw_prediction,  # this was updated in line_search
        )

    def line_search(self, X, y, sample_weight):
        # Use R' instead of X
        super().line_search(X=self.R.T, y=y, sample_weight=sample_weight)

    def check_convergence(self, X, y, sample_weight):
        # Use R' instead of X
        super().check_convergence(X=self.R.T, y=y, sample_weight=sample_weight)

    def finalize(self, X, y, sample_weight):
        n_features = X.shape[1]
        w, intercept = self.linear_loss.weight_intercept(self.coef)
        self.coef_original[:n_features] = self.Q @ w
        if self.linear_loss.fit_intercept:
            self.coef_original[-1] = intercept
        self.coef = self.coef_original


class LSMRNewtonSolver(NewtonSolver):
    """LSMR based Newton solver.

    The inner solver uses LSMR [1] after the Newton update is cast into the iteratively
    reweighted least squares (IRLS) formulation. This means

        H @ coef_newton = -G

    with

        G = X.T @ g + l2_reg_strength * coef
        H = X.T @ diag(h) @ X + l2_reg_strength * identity
        g = loss.gradient = pointwise gradient
        h = loss.hessian = pointwise hessian

    is cast as a least squares problem

        min ||A @ newton_step - b||_2^2

    with

        A = [                    sqrt(h) * X]
            [sqrt(l2_reg_strength) * sqrt(P)]
        b = [                                - g / sqrt(h)]
            [- sqrt(l2_reg_strength) * sqrt(P) @ self.coef]
        P = penalty matrix in 1/2 w @ P @ w,
            for a pure L2 penalty without intercept it equals the identity matrix.

    The normal equation if this least squares problem is again: H @ coef_newton = -G.

    Note that this solver can naturally deal with sparse X.

    References
    ----------
    .. [1] :arxiv:`Fong & Saunders "LSMR: An iterative algorithm for sparse
           least-squares problems" <1006.0758>`
           See also
           https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.lsmr.html

    """  # noqa: E501

    def setup(self, X, y, sample_weight):
        """Setup.

        If None, initializes:
            - self.coef
        Sets:
            - self.raw_prediction
            - self.loss_value
            - self.g = pointwise gradient
            - self.h = pointwise hessian
            - self.gradient
            - self.sqrt_P = sqrt(l2_reg_strength) * sqrt(P)
            - self.A_norm
            - self.gradient_step
        """
        super().setup(X=X, y=y, sample_weight=sample_weight)
        (self.g, self.h,) = self.linear_loss.base_loss.init_gradient_and_hessian(
            n_samples=X.shape[0], dtype=X.dtype
        )
        # For a general (symmetric) penalty matrix P, we can use any square root of it,
        # e.g. the Cholesky decomposition. Here, we can use the identity matrix and
        # handle the intercept.
        n_features = X.shape[1]
        # We use a 1-d array instead of a 2-d diagonal array to save memory. We also
        # simply omit to add a zero at the end for the intercept.
        self.sqrt_P = np.full(
            shape=n_features, fill_value=np.sqrt(self.l2_reg_strength), dtype=X.dtype
        )

        # Initially, set Frobenius norm of A as if h = 1
        # => ||A||^2 = ||X||^2 + sqrt(l2_reg_strength) ||sqrt(P)||^2
        # if scipy.sparse.issparse(X):
        #     A_norm = scipy.sparse.linalg.norm(X) ** 2
        # else:
        #     A_norm = scipy.linalg.norm(X) ** 2
        # A_norm += scipy.linalg.norm(self.sqrt_P) ** 2
        # self.A_norm = np.sqrt(A_norm)
        # As this all is a bit costly, we make life easier and start with 1:
        self.A_norm = 1
        self.r_norm = 1

        # needed for inner_solve
        self.gradient_step = 0

    def update_gradient_hessian(self, X, y, sample_weight):
        """Update gradient and hessian.

        Update pointwise gradient and hessian, self.g and self.h,
        as well as the full gradient, self.gradient.
        """
        self.linear_loss.base_loss.gradient_hessian(
            y_true=y,
            raw_prediction=self.raw_prediction,  # this was updated in line_search
            sample_weight=sample_weight,
            gradient_out=self.g,
            hessian_out=self.h,
            n_threads=self.n_threads,
        )
        # For non-canonical link functions and far away from the optimum, we take
        # care that the hessian is at least non-negative. Tiny positive values are set
        # to zero, too.
        eps = 16 * np.finfo(y.dtype).eps
        self.h[self.h <= eps] = 0

        n_features = X.shape[1]
        # This duplicates a bit of code from LinearModelLoss.gradient.
        weights, _ = self.linear_loss.weight_intercept(self.coef)
        self.gradient = np.empty_like(self.coef, dtype=self.coef.dtype)
        self.gradient[:n_features] = X.T @ self.g + self.l2_reg_strength * weights
        if self.linear_loss.fit_intercept:
            self.gradient[-1] = self.g.sum()

    def inner_solve(self, X, y, sample_weight):
        """Compute Newton step.

        Sets self.coef_newton via LSMR.
        Also sets self.A_norm and self.r_norm for better control over tolerance in
        LSMR.
        """
        n_samples, n_features = X.shape
        sqrt_h = np.sqrt(self.h)
        # Take care of h = 0. Tiny h are already set to 0.
        # If h = 0 we can exclude the corresponding row of X such that the value of b
        # becomes irrelevant. We set it -g as if h = 1.
        g_over_h_sqrt = self.g
        g_over_h_sqrt[sqrt_h > 0] /= sqrt_h[sqrt_h > 0]

        b = np.r_[-g_over_h_sqrt, -self.sqrt_P * self.coef[:n_features]]

        if self.linear_loss.fit_intercept:
            n_dof = n_features + 1

            def matvec(x):
                # A @ x with intercept
                # We assume self.sqrt_P to be 1-d array of shape (n_features,),
                # representing a diagonal matrix.
                return np.r_[sqrt_h * (X @ x[:-1] + x[-1]), self.sqrt_P * x[:-1]]

            def rmatvec(x):
                # A.T @ x with intercept
                return np.r_[
                    X.T @ (sqrt_h * x[:n_samples]) + self.sqrt_P * x[n_samples:],
                    sqrt_h @ x[:n_samples],
                ]

        else:
            n_dof = n_features

            def matvec(x):
                # A @ x without intercept
                return np.r_[sqrt_h * (X @ x), self.sqrt_P * x]

            def rmatvec(x):
                # A.T @ x without intercept
                return X.T @ (sqrt_h * x[:n_samples]) + self.sqrt_P * x[n_samples:]

        # Note that initializing LinearOperator seems to have some surprisingly sizable
        # overhead.
        A = scipy.sparse.linalg.LinearOperator(
            shape=(n_samples + n_features, n_dof), matvec=matvec, rmatvec=rmatvec
        )
        # Note that the choice of atol is essential for stability and for computation
        # time. For n_samples > n_features, we most certainly have a least squares
        # problem (no solution to the linear equation A x = b), such that the following
        # stopping criterion with residual r = b - A x applies:
        #   ||A' r|| <= atol * ||A|| * ||r||.
        # As we get the Frobenius norm of A and the norm of r, ||A|| and ||r||
        # respectively, for free by LSMR, we use it to set a tighter atol by dividing
        # by ||A|| * min(1, ||r||) which is very likely larger than 1. The effective
        # stopping criterion becomes approximately
        #   ||A' r|| <= self.tol * ||r||   with   x = coef_newton   and
        #   1/2 * ||r||^2 = 1/2 * x X' diag(h) X x + g X x
        #                 + 1/2 * l2_reg_strength * (x+x0) P (x+x0)
        #                 + 1/2 *||g/sqrt(h)||^2
        # Note that coef=x+x0 is just the solution after an iteration. In particular
        # note that this is just the Taylor series of the objective with the zero
        # order term obj(x=0) replaced by 1/2 * ||g/sqrt(h)||^2.
        result = scipy.sparse.linalg.lsmr(
            A,
            b,
            damp=0,
            atol=self.tol / (max(1, self.A_norm) * max(1, self.r_norm)),
            btol=self.tol,
            show=self.verbose >= 3,
        )
        # We store the estimated Frobenius norm of A and norm of residual r in
        # self.A_norm and self.r_norm for tolerance of next iteration.
        (
            self.coef_newton,
            istop,
            itn,
            self.r_norm,
            normar,
            self.A_norm,
            conda,
            normx,
        ) = result
        # LSMR reached maxiter.
        eps = 4 * np.finfo(self.gradient.dtype).eps
        if istop == 7:
            if self.gradient_step == 0:
                # We only need to throw this warning once.
                warnings.warn(
                    f"The inner solver of {self.__class__.__name__} reached "
                    "maxiter={itn} before the other stopping conditions were "
                    "satisfied at iteration #{self.iteration}. It will now try a "
                    "simple gradient step. "
                    "Note that this warning is only raised once, the problem may, "
                    " however, occur in several or all iterations. Set verbose >= 1"
                    " to get more information.\n"
                    "This may be cause by an ill-conditioned or singular hessian. Your"
                    " options are to use another solver or to avoid such situation"
                    " in the first place. Possible  remedies are removing collinear"
                    " features of X or increasing the penalization strengths.",
                    ConvergenceWarning,
                )
            self.gradient_step += 1
            if self.verbose:
                print(
                    "  The inner solver had problems to converge and resorts to a "
                    "simple gradient step."
                )
            # We add 1e-3 to the diagonal hessian part to make in invertible and to
            # restrict coef_newton to at most ~1e3. The line search considerst step
            # sizes until 1e-6 * newton_step ~1e-3 * newton_step.
            # Deviding by self.iteration ensures (slow) convergence.
            eps = 1e-3 / self.iteration
            self.coef_newton = -self.gradient / (np.sqrt(self.A_norm) + eps)

    def compute_d2(self, X):
        """Compute square of Newton decrement."""
        weights, intercept, raw_prediction = self.linear_loss.weight_intercept_raw(
            self.coef_newton, X
        )
        d2 = np.sum(raw_prediction * self.h * raw_prediction)
        d2 += 2 * self.linear_loss.l2_penalty(weights, self.l2_reg_strength)
        return d2


class _GeneralizedLinearRegressor(RegressorMixin, BaseEstimator):
    """Regression via a penalized Generalized Linear Model (GLM).

    GLMs based on a reproductive Exponential Dispersion Model (EDM) aim at fitting and
    predicting the mean of the target y as y_pred=h(X*w) with coefficients w.
    Therefore, the fit minimizes the following objective function with L2 priors as
    regularizer::

        1/(2*sum(s_i)) * sum(s_i * deviance(y_i, h(x_i*w)) + 1/2 * alpha * ||w||_2^2

    with inverse link function h, s=sample_weight and per observation (unit) deviance
    deviance(y_i, h(x_i*w)). Note that for an EDM, 1/2 * deviance is the negative
    log-likelihood up to a constant (in w) term.
    The parameter ``alpha`` corresponds to the lambda parameter in glmnet.

    Instead of implementing the EDM family and a link function separately, we directly
    use the loss functions `from sklearn._loss` which have the link functions included
    in them for performance reasons. We pick the loss functions that implement
    (1/2 times) EDM deviances.

    Read more in the :ref:`User Guide <Generalized_linear_regression>`.

    .. versionadded:: 0.23

    Parameters
    ----------
    alpha : float, default=1
        Constant that multiplies the penalty term and thus determines the
        regularization strength. ``alpha = 0`` is equivalent to unpenalized
        GLMs. In this case, the design matrix `X` must have full column rank
        (no collinearities).
        Values must be in the range `[0.0, inf)`.

    fit_intercept : bool, default=True
        Specifies if a constant (a.k.a. bias or intercept) should be
        added to the linear predictor (X @ coef + intercept).

    solver : {'lbfgs', 'newton-cholesky', 'newton-qr-cholesky'}, default='lbfgs'
        Algorithm to use in the optimization problem:

        'lbfgs'
            Calls scipy's L-BFGS-B optimizer.

        'newton-cholesky'
            Uses Newton-Raphson steps (equals iterated reweighted least squares) with
            an inner cholesky based solver.

        'newton-qr-cholesky'
            Same as 'newton-cholesky' but uses a qr decomposition of X.T. This solver
            is better for n_features >> n_samples than 'newton-cholesky'.

    max_iter : int, default=100
        The maximal number of iterations for the solver.
        Values must be in the range `[1, inf)`.

    tol : float, default=1e-4
        Stopping criterion. For the lbfgs solver,
        the iteration will stop when ``max{|g_j|, j = 1, ..., d} <= tol``
        where ``g_j`` is the j-th component of the gradient (derivative) of
        the objective function.
        Values must be in the range `(0.0, inf)`.

    warm_start : bool, default=False
        If set to ``True``, reuse the solution of the previous call to ``fit``
        as initialization for ``coef_`` and ``intercept_``.

    verbose : int, default=0
        For the lbfgs solver set verbose to any positive number for verbosity.
        Values must be in the range `[0, inf)`.

    Attributes
    ----------
    coef_ : array of shape (n_features,)
        Estimated coefficients for the linear predictor (`X @ coef_ +
        intercept_`) in the GLM.

    intercept_ : float
        Intercept (a.k.a. bias) added to linear predictor.

    n_iter_ : int
        Actual number of iterations used in the solver.

    _base_loss : BaseLoss, default=HalfSquaredError()
        This is set during fit via `self._get_loss()`.
        A `_base_loss` contains a specific loss function as well as the link
        function. The loss to be minimized specifies the distributional assumption of
        the GLM, i.e. the distribution from the EDM. Here are some examples:

        =======================  ========  ==========================
        _base_loss               Link      Target Domain
        =======================  ========  ==========================
        HalfSquaredError         identity  y any real number
        HalfPoissonLoss          log       0 <= y
        HalfGammaLoss            log       0 < y
        HalfTweedieLoss          log       dependend on tweedie power
        HalfTweedieLossIdentity  identity  dependend on tweedie power
        =======================  ========  ==========================

        The link function of the GLM, i.e. mapping from linear predictor
        `X @ coeff + intercept` to prediction `y_pred`. For instance, with a log link,
        we have `y_pred = exp(X @ coeff + intercept)`.
    """

    def __init__(
        self,
        *,
        alpha=1.0,
        fit_intercept=True,
        solver="lbfgs",
        max_iter=100,
        tol=1e-4,
        warm_start=False,
        verbose=0,
    ):
        self.alpha = alpha
        self.fit_intercept = fit_intercept
        self.solver = solver
        self.max_iter = max_iter
        self.tol = tol
        self.warm_start = warm_start
        self.verbose = verbose

    def fit(self, X, y, sample_weight=None):
        """Fit a Generalized Linear Model.

        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features)
            Training data.

        y : array-like of shape (n_samples,)
            Target values.

        sample_weight : array-like of shape (n_samples,), default=None
            Sample weights.

        Returns
        -------
        self : object
            Fitted model.
        """
        check_scalar(
            self.alpha,
            name="alpha",
            target_type=numbers.Real,
            min_val=0.0,
            include_boundaries="left",
        )
        if not isinstance(self.fit_intercept, bool):
            raise ValueError(
                "The argument fit_intercept must be bool; got {0}".format(
                    self.fit_intercept
                )
            )
        # We allow for NewtonSolver classes but do not make them public in the
        # docstrings. This facilitates testing and benchmarking.
        if self.solver not in [
            "lbfgs",
            "newton-cholesky",
            "newton-qr-cholesky",
            "newton-lsmr",
        ] and not (
            isinstance(self.solver, type) and issubclass(self.solver, NewtonSolver)
        ):
            raise ValueError(
                f"{self.__class__.__name__} supports only solvers 'lbfgs',"
                " 'newton-cholesky', 'newton-qr-cholesky' and 'newton-lsmr'; got"
                f" {self.solver}"
            )
        solver = self.solver
        check_scalar(
            self.max_iter,
            name="max_iter",
            target_type=numbers.Integral,
            min_val=1,
        )
        check_scalar(
            self.tol,
            name="tol",
            target_type=numbers.Real,
            min_val=0.0,
            include_boundaries="neither",
        )
        check_scalar(
            self.verbose,
            name="verbose",
            target_type=numbers.Integral,
            min_val=0,
        )
        if not isinstance(self.warm_start, bool):
            raise ValueError(
                "The argument warm_start must be bool; got {0}".format(self.warm_start)
            )

        X, y = self._validate_data(
            X,
            y,
            accept_sparse=["csc", "csr"],
            dtype=[np.float64, np.float32],
            y_numeric=True,
            multi_output=False,
        )

        # required by losses
        if solver == "lbfgs":
            # lbfgs will force coef and therefore raw_prediction to be float64. The
            # base_loss needs y, X @ coef and sample_weight all of same dtype
            # (and contiguous).
            loss_dtype = np.float64
        else:
            loss_dtype = min(max(y.dtype, X.dtype), np.float64)
        y = check_array(y, dtype=loss_dtype, order="C", ensure_2d=False)

        # TODO: We could support samples_weight=None as the losses support it.
        # Note that _check_sample_weight calls check_array(order="C") required by
        # losses.
        sample_weight = _check_sample_weight(sample_weight, X, dtype=loss_dtype)

        n_samples, n_features = X.shape
        self._base_loss = self._get_loss()

        linear_loss = LinearModelLoss(
            base_loss=self._base_loss,
            fit_intercept=self.fit_intercept,
        )

        if not linear_loss.base_loss.in_y_true_range(y):
            raise ValueError(
                "Some value(s) of y are out of the valid range of the loss"
                f" {self._base_loss.__class__.__name__!r}."
            )

        # TODO: if alpha=0 check that X is not rank deficient

        # IMPORTANT NOTE: Rescaling of sample_weight:
        # We want to minimize
        #     obj = 1/(2*sum(sample_weight)) * sum(sample_weight * deviance)
        #         + 1/2 * alpha * L2,
        # with
        #     deviance = 2 * loss.
        # The objective is invariant to multiplying sample_weight by a constant. We
        # choose this constant such that sum(sample_weight) = 1. Thus, we end up with
        #     obj = sum(sample_weight * loss) + 1/2 * alpha * L2.
        # Note that LinearModelLoss.loss() computes sum(sample_weight * loss).
        sample_weight = sample_weight / sample_weight.sum()

        if self.warm_start and hasattr(self, "coef_"):
            if self.fit_intercept:
                # LinearModelLoss needs intercept at the end of coefficient array.
                coef = np.concatenate((self.coef_, np.array([self.intercept_])))
            else:
                coef = self.coef_
            coef = coef.astype(loss_dtype, copy=False)
        else:
            if self.fit_intercept:
                coef = np.zeros(n_features + 1, dtype=loss_dtype)
                coef[-1] = linear_loss.base_loss.link.link(
                    np.average(y, weights=sample_weight)
                )
            else:
                coef = np.zeros(n_features, dtype=loss_dtype)

        l2_reg_strength = self.alpha
        n_threads = _openmp_effective_n_threads()

        # Algorithms for optimization:
        # Note again that our losses implement 1/2 * deviance.
        if solver == "lbfgs":
            func = linear_loss.loss_gradient

            opt_res = scipy.optimize.minimize(
                func,
                coef,
                method="L-BFGS-B",
                jac=True,
                options={
                    "maxiter": self.max_iter,
                    "maxls": 30,  # default is 20
                    "iprint": (self.verbose > 0) - 1,
                    "gtol": self.tol,
                    "ftol": 64 * np.finfo(np.float64).eps,  # lbfgs is float64 land.
                },
                args=(X, y, sample_weight, l2_reg_strength, n_threads),
            )
            self.n_iter_ = _check_optimize_result("lbfgs", opt_res)
            coef = opt_res.x
        elif solver in ["newton-cholesky", "newton-qr-cholesky", "newton-lsmr"]:
            sol_dict = {
                "newton-cholesky": CholeskyNewtonSolver,
                "newton-qr-cholesky": QRCholeskyNewtonSolver,
                "newton-lsmr": LSMRNewtonSolver,
            }
            sol = sol_dict[solver](
                coef=coef,
                linear_loss=linear_loss,
                l2_reg_strength=l2_reg_strength,
                tol=self.tol,
                max_iter=self.max_iter,
                n_threads=n_threads,
                verbose=self.verbose,
            )
            coef = sol.solve(X, y, sample_weight)
            self.n_iter_ = sol.iteration
        elif issubclass(solver, NewtonSolver):
            sol = solver(
                coef=coef,
                linear_loss=linear_loss,
                l2_reg_strength=l2_reg_strength,
                tol=self.tol,
                max_iter=self.max_iter,
                n_threads=n_threads,
            )
            coef = sol.solve(X, y, sample_weight)

        if self.fit_intercept:
            self.intercept_ = coef[-1]
            self.coef_ = coef[:-1]
        else:
            # set intercept to zero as the other linear models do
            self.intercept_ = 0.0
            self.coef_ = coef

        return self

    def _linear_predictor(self, X):
        """Compute the linear_predictor = `X @ coef_ + intercept_`.

        Note that we often use the term raw_prediction instead of linear predictor.

        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features)
            Samples.

        Returns
        -------
        y_pred : array of shape (n_samples,)
            Returns predicted values of linear predictor.
        """
        check_is_fitted(self)
        X = self._validate_data(
            X,
            accept_sparse=["csr", "csc", "coo"],
            dtype=[np.float64, np.float32],
            ensure_2d=True,
            allow_nd=False,
            reset=False,
        )
        return X @ self.coef_ + self.intercept_

    def predict(self, X):
        """Predict using GLM with feature matrix X.

        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features)
            Samples.

        Returns
        -------
        y_pred : array of shape (n_samples,)
            Returns predicted values.
        """
        # check_array is done in _linear_predictor
        raw_prediction = self._linear_predictor(X)
        y_pred = self._base_loss.link.inverse(raw_prediction)
        return y_pred

    def score(self, X, y, sample_weight=None):
        """Compute D^2, the percentage of deviance explained.

        D^2 is a generalization of the coefficient of determination R^2.
        R^2 uses squared error and D^2 uses the deviance of this GLM, see the
        :ref:`User Guide <regression_metrics>`.

        D^2 is defined as
        :math:`D^2 = 1-\\frac{D(y_{true},y_{pred})}{D_{null}}`,
        :math:`D_{null}` is the null deviance, i.e. the deviance of a model
        with intercept alone, which corresponds to :math:`y_{pred} = \\bar{y}`.
        The mean :math:`\\bar{y}` is averaged by sample_weight.
        Best possible score is 1.0 and it can be negative (because the model
        can be arbitrarily worse).

        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features)
            Test samples.

        y : array-like of shape (n_samples,)
            True values of target.

        sample_weight : array-like of shape (n_samples,), default=None
            Sample weights.

        Returns
        -------
        score : float
            D^2 of self.predict(X) w.r.t. y.
        """
        # TODO: Adapt link to User Guide in the docstring, once
        # https://github.com/scikit-learn/scikit-learn/pull/22118 is merged.
        #
        # Note, default score defined in RegressorMixin is R^2 score.
        # TODO: make D^2 a score function in module metrics (and thereby get
        #       input validation and so on)
        raw_prediction = self._linear_predictor(X)  # validates X
        # required by losses
        y = check_array(y, dtype=raw_prediction.dtype, order="C", ensure_2d=False)

        if sample_weight is not None:
            # Note that _check_sample_weight calls check_array(order="C") required by
            # losses.
            sample_weight = _check_sample_weight(sample_weight, X, dtype=y.dtype)

        base_loss = self._base_loss

        if not base_loss.in_y_true_range(y):
            raise ValueError(
                "Some value(s) of y are out of the valid range of the loss"
                f" {base_loss.__name__}."
            )

        # Note that constant_to_optimal_zero is already multiplied by sample_weight.
        constant = np.mean(base_loss.constant_to_optimal_zero(y_true=y))
        if sample_weight is not None:
            constant *= sample_weight.shape[0] / np.sum(sample_weight)

        # Missing factor of 2 in deviance cancels out.
        deviance = base_loss(
            y_true=y,
            raw_prediction=raw_prediction,
            sample_weight=sample_weight,
            n_threads=1,
        )
        y_mean = base_loss.link.link(np.average(y, weights=sample_weight))
        deviance_null = base_loss(
            y_true=y,
            raw_prediction=np.tile(y_mean, y.shape[0]),
            sample_weight=sample_weight,
            n_threads=1,
        )
        return 1 - (deviance + constant) / (deviance_null + constant)

    def _more_tags(self):
        # Create instance of BaseLoss if fit wasn't called yet. This is necessary as
        # TweedieRegressor might set the used loss during fit different from
        # self._base_loss.
        base_loss = self._get_loss()
        return {"requires_positive_y": not base_loss.in_y_true_range(-1.0)}

    def _get_loss(self):
        """This is only necessary because of the link and power arguments of the
        TweedieRegressor.

        Note that we do not need to pass sample_weight to the loss class as this is
        only needed to set loss.constant_hessian on which GLMs do not rely.
        """
        return HalfSquaredError()

    # TODO(1.3): remove
    @deprecated(  # type: ignore
        "Attribute `family` was deprecated in version 1.1 and will be removed in 1.3."
    )
    @property
    def family(self):
        """Ensure backward compatibility for the time of deprecation."""
        if isinstance(self, PoissonRegressor):
            return "poisson"
        elif isinstance(self, GammaRegressor):
            return "gamma"
        elif isinstance(self, TweedieRegressor):
            return TweedieDistribution(power=self.power)
        else:
            raise ValueError(  # noqa
                "This should never happen. You presumably accessed the deprecated "
                "`family` attribute from a subclass of the private scikit-learn class "
                "_GeneralizedLinearRegressor."
            )


class PoissonRegressor(_GeneralizedLinearRegressor):
    """Generalized Linear Model with a Poisson distribution.

    This regressor uses the 'log' link function.

    Read more in the :ref:`User Guide <Generalized_linear_regression>`.

    .. versionadded:: 0.23

    Parameters
    ----------
    alpha : float, default=1
        Constant that multiplies the penalty term and thus determines the
        regularization strength. ``alpha = 0`` is equivalent to unpenalized
        GLMs. In this case, the design matrix `X` must have full column rank
        (no collinearities).
        Values must be in the range `[0.0, inf)`.

    fit_intercept : bool, default=True
        Specifies if a constant (a.k.a. bias or intercept) should be
        added to the linear predictor (X @ coef + intercept).

    solver : {'lbfgs', 'newton-cholesky'}, default='lbfgs'
        Algorithm to use in the optimization problem:

        'lbfgs'
            Calls scipy's L-BFGS-B optimizer.

        'newton-cholesky'
            Uses Newton-Raphson steps (equals iterated reweighted least squares) with
            an inner cholesky based solver.

        'newton-qr-cholesky'
            Same as 'newton-cholesky' but uses a qr decomposition of X.T. This solver
            is better for n_features >> n_samples than 'newton-cholesky'.

    max_iter : int, default=100
        The maximal number of iterations for the solver.
        Values must be in the range `[1, inf)`.

    tol : float, default=1e-4
        Stopping criterion. For the lbfgs solver,
        the iteration will stop when ``max{|g_j|, j = 1, ..., d} <= tol``
        where ``g_j`` is the j-th component of the gradient (derivative) of
        the objective function.
        Values must be in the range `(0.0, inf)`.

    warm_start : bool, default=False
        If set to ``True``, reuse the solution of the previous call to ``fit``
        as initialization for ``coef_`` and ``intercept_`` .

    verbose : int, default=0
        For the lbfgs solver set verbose to any positive number for verbosity.
        Values must be in the range `[0, inf)`.

    Attributes
    ----------
    coef_ : array of shape (n_features,)
        Estimated coefficients for the linear predictor (`X @ coef_ +
        intercept_`) in the GLM.

    intercept_ : float
        Intercept (a.k.a. bias) added to linear predictor.

    n_features_in_ : int
        Number of features seen during :term:`fit`.

        .. versionadded:: 0.24

    feature_names_in_ : ndarray of shape (`n_features_in_`,)
        Names of features seen during :term:`fit`. Defined only when `X`
        has feature names that are all strings.

        .. versionadded:: 1.0

    n_iter_ : int
        Actual number of iterations used in the solver.

    See Also
    --------
    TweedieRegressor : Generalized Linear Model with a Tweedie distribution.

    Examples
    --------
    >>> from sklearn import linear_model
    >>> clf = linear_model.PoissonRegressor()
    >>> X = [[1, 2], [2, 3], [3, 4], [4, 3]]
    >>> y = [12, 17, 22, 21]
    >>> clf.fit(X, y)
    PoissonRegressor()
    >>> clf.score(X, y)
    0.990...
    >>> clf.coef_
    array([0.121..., 0.158...])
    >>> clf.intercept_
    2.088...
    >>> clf.predict([[1, 1], [3, 4]])
    array([10.676..., 21.875...])
    """

    def __init__(
        self,
        *,
        alpha=1.0,
        fit_intercept=True,
        solver="lbfgs",
        max_iter=100,
        tol=1e-4,
        warm_start=False,
        verbose=0,
    ):
        super().__init__(
            alpha=alpha,
            fit_intercept=fit_intercept,
            solver=solver,
            max_iter=max_iter,
            tol=tol,
            warm_start=warm_start,
            verbose=verbose,
        )

    def _get_loss(self):
        return HalfPoissonLoss()


class GammaRegressor(_GeneralizedLinearRegressor):
    """Generalized Linear Model with a Gamma distribution.

    This regressor uses the 'log' link function.

    Read more in the :ref:`User Guide <Generalized_linear_regression>`.

    .. versionadded:: 0.23

    Parameters
    ----------
    alpha : float, default=1
        Constant that multiplies the penalty term and thus determines the
        regularization strength. ``alpha = 0`` is equivalent to unpenalized
        GLMs. In this case, the design matrix `X` must have full column rank
        (no collinearities).
        Values must be in the range `[0.0, inf)`.

    fit_intercept : bool, default=True
        Specifies if a constant (a.k.a. bias or intercept) should be
        added to the linear predictor (X @ coef + intercept).

    solver : {'lbfgs', 'newton-cholesky'}, default='lbfgs'
        Algorithm to use in the optimization problem:

        'lbfgs'
            Calls scipy's L-BFGS-B optimizer.

        'newton-cholesky'
            Uses Newton-Raphson steps (equals iterated reweighted least squares) with
            an inner cholesky based solver.

        'newton-qr-cholesky'
            Same as 'newton-cholesky' but uses a qr decomposition of X.T. This solver
            is better for n_features >> n_samples than 'newton-cholesky'.

    max_iter : int, default=100
        The maximal number of iterations for the solver.
        Values must be in the range `[1, inf)`.

    tol : float, default=1e-4
        Stopping criterion. For the lbfgs solver,
        the iteration will stop when ``max{|g_j|, j = 1, ..., d} <= tol``
        where ``g_j`` is the j-th component of the gradient (derivative) of
        the objective function.
        Values must be in the range `(0.0, inf)`.

    warm_start : bool, default=False
        If set to ``True``, reuse the solution of the previous call to ``fit``
        as initialization for ``coef_`` and ``intercept_`` .

    verbose : int, default=0
        For the lbfgs solver set verbose to any positive number for verbosity.
        Values must be in the range `[0, inf)`.

    Attributes
    ----------
    coef_ : array of shape (n_features,)
        Estimated coefficients for the linear predictor (`X * coef_ +
        intercept_`) in the GLM.

    intercept_ : float
        Intercept (a.k.a. bias) added to linear predictor.

    n_features_in_ : int
        Number of features seen during :term:`fit`.

        .. versionadded:: 0.24

    n_iter_ : int
        Actual number of iterations used in the solver.

    feature_names_in_ : ndarray of shape (`n_features_in_`,)
        Names of features seen during :term:`fit`. Defined only when `X`
        has feature names that are all strings.

        .. versionadded:: 1.0

    See Also
    --------
    PoissonRegressor : Generalized Linear Model with a Poisson distribution.
    TweedieRegressor : Generalized Linear Model with a Tweedie distribution.

    Examples
    --------
    >>> from sklearn import linear_model
    >>> clf = linear_model.GammaRegressor()
    >>> X = [[1, 2], [2, 3], [3, 4], [4, 3]]
    >>> y = [19, 26, 33, 30]
    >>> clf.fit(X, y)
    GammaRegressor()
    >>> clf.score(X, y)
    0.773...
    >>> clf.coef_
    array([0.072..., 0.066...])
    >>> clf.intercept_
    2.896...
    >>> clf.predict([[1, 0], [2, 8]])
    array([19.483..., 35.795...])
    """

    def __init__(
        self,
        *,
        alpha=1.0,
        fit_intercept=True,
        solver="lbfgs",
        max_iter=100,
        tol=1e-4,
        warm_start=False,
        verbose=0,
    ):
        super().__init__(
            alpha=alpha,
            fit_intercept=fit_intercept,
            solver=solver,
            max_iter=max_iter,
            tol=tol,
            warm_start=warm_start,
            verbose=verbose,
        )

    def _get_loss(self):
        return HalfGammaLoss()


class TweedieRegressor(_GeneralizedLinearRegressor):
    """Generalized Linear Model with a Tweedie distribution.

    This estimator can be used to model different GLMs depending on the
    ``power`` parameter, which determines the underlying distribution.

    Read more in the :ref:`User Guide <Generalized_linear_regression>`.

    .. versionadded:: 0.23

    Parameters
    ----------
    power : float, default=0
            The power determines the underlying target distribution according
            to the following table:

            +-------+------------------------+
            | Power | Distribution           |
            +=======+========================+
            | 0     | Normal                 |
            +-------+------------------------+
            | 1     | Poisson                |
            +-------+------------------------+
            | (1,2) | Compound Poisson Gamma |
            +-------+------------------------+
            | 2     | Gamma                  |
            +-------+------------------------+
            | 3     | Inverse Gaussian       |
            +-------+------------------------+

            For ``0 < power < 1``, no distribution exists.

    alpha : float, default=1
        Constant that multiplies the penalty term and thus determines the
        regularization strength. ``alpha = 0`` is equivalent to unpenalized
        GLMs. In this case, the design matrix `X` must have full column rank
        (no collinearities).
        Values must be in the range `[0.0, inf)`.

    fit_intercept : bool, default=True
        Specifies if a constant (a.k.a. bias or intercept) should be
        added to the linear predictor (X @ coef + intercept).

    link : {'auto', 'identity', 'log'}, default='auto'
        The link function of the GLM, i.e. mapping from linear predictor
        `X @ coeff + intercept` to prediction `y_pred`. Option 'auto' sets
        the link depending on the chosen `power` parameter as follows:

        - 'identity' for ``power <= 0``, e.g. for the Normal distribution
        - 'log' for ``power > 0``, e.g. for Poisson, Gamma and Inverse Gaussian
          distributions

    solver : {'lbfgs', 'newton-cholesky'}, default='lbfgs'
        Algorithm to use in the optimization problem:

        'lbfgs'
            Calls scipy's L-BFGS-B optimizer.

        'newton-cholesky'
            Uses Newton-Raphson steps (equals iterated reweighted least squares) with
            an inner cholesky based solver.

        'newton-qr-cholesky'
            Same as 'newton-cholesky' but uses a qr decomposition of X.T. This solver
            is better for n_features >> n_samples than 'newton-cholesky'.

    max_iter : int, default=100
        The maximal number of iterations for the solver.
        Values must be in the range `[1, inf)`.

    tol : float, default=1e-4
        Stopping criterion. For the lbfgs solver,
        the iteration will stop when ``max{|g_j|, j = 1, ..., d} <= tol``
        where ``g_j`` is the j-th component of the gradient (derivative) of
        the objective function.
        Values must be in the range `(0.0, inf)`.

    warm_start : bool, default=False
        If set to ``True``, reuse the solution of the previous call to ``fit``
        as initialization for ``coef_`` and ``intercept_`` .

    verbose : int, default=0
        For the lbfgs solver set verbose to any positive number for verbosity.
        Values must be in the range `[0, inf)`.

    Attributes
    ----------
    coef_ : array of shape (n_features,)
        Estimated coefficients for the linear predictor (`X @ coef_ +
        intercept_`) in the GLM.

    intercept_ : float
        Intercept (a.k.a. bias) added to linear predictor.

    n_iter_ : int
        Actual number of iterations used in the solver.

    n_features_in_ : int
        Number of features seen during :term:`fit`.

        .. versionadded:: 0.24

    feature_names_in_ : ndarray of shape (`n_features_in_`,)
        Names of features seen during :term:`fit`. Defined only when `X`
        has feature names that are all strings.

        .. versionadded:: 1.0

    See Also
    --------
    PoissonRegressor : Generalized Linear Model with a Poisson distribution.
    GammaRegressor : Generalized Linear Model with a Gamma distribution.

    Examples
    --------
    >>> from sklearn import linear_model
    >>> clf = linear_model.TweedieRegressor()
    >>> X = [[1, 2], [2, 3], [3, 4], [4, 3]]
    >>> y = [2, 3.5, 5, 5.5]
    >>> clf.fit(X, y)
    TweedieRegressor()
    >>> clf.score(X, y)
    0.839...
    >>> clf.coef_
    array([0.599..., 0.299...])
    >>> clf.intercept_
    1.600...
    >>> clf.predict([[1, 1], [3, 4]])
    array([2.500..., 4.599...])
    """

    def __init__(
        self,
        *,
        power=0.0,
        alpha=1.0,
        fit_intercept=True,
        link="auto",
        solver="lbfgs",
        max_iter=100,
        tol=1e-4,
        warm_start=False,
        verbose=0,
    ):
        super().__init__(
            alpha=alpha,
            fit_intercept=fit_intercept,
            solver=solver,
            max_iter=max_iter,
            tol=tol,
            warm_start=warm_start,
            verbose=verbose,
        )
        self.link = link
        self.power = power

    def _get_loss(self):
        if self.link == "auto":
            if self.power <= 0:
                # identity link
                return HalfTweedieLossIdentity(power=self.power)
            else:
                # log link
                return HalfTweedieLoss(power=self.power)
        elif self.link == "log":
            return HalfTweedieLoss(power=self.power)
        elif self.link == "identity":
            return HalfTweedieLossIdentity(power=self.power)
        else:
            raise ValueError(
                "The link must be an element of ['auto', 'identity', 'log']; "
                f"got (link={self.link!r})"
            )
