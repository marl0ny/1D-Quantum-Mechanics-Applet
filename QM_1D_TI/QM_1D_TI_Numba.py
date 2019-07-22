import numpy as np
from numba import jit, prange, c16, f8
from numba.types import Tuple

@jit('c16[:](c16[:,:], c16[:])', parallel=True, cache=True, nopython=True)
def _time_evolve_wavefunction(U, psix):
    return np.dot(U, psix)

@jit('c16[:,:](c16[:], f8, f8, i8, f8, f8)', parallel=True, nopython=True)
def _construct_U(V, m, hbar, N, dx, dt):

    #Initialize A and B matrices
    A = np.zeros((N, N), np.complex128)
    B = np.zeros((N, N), np.complex128)

    # \Delta t \frac{i \hbar}{2m \Delta x^2}
    #K = np.dtype(np.complex128)
    K=(dt*1.0j*hbar)/(4*m*dx**2)

    # \frac{\Delta t i \hbar}{2}
    #J = np.dtype(np.complex128)
    J=(dt*1.0j)/(2*hbar)

    #Initialize the constant,
    #nonzero elements of the A and B matrices
    a1 = 1 + 2*K
    a2 = -K
    b1 = 1 - 2*K
    b2 = K

    #Construct the A and B matrices
    for i in range (N):
        for l in range (N):
            if (i == l):

                A[i][l] = a1 + J*V[i]
                B[i][l] = b1 - J*V[i]

            elif (l == (i + 1)):

                A[i][l] = a2
                A[l][i] = a2

                B[i][l] = b2
                B[l][i] = b2

    return np.dot(np.linalg.inv(A), B)

@jit('Tuple((c16[:], c16[:,:]))(c16[:,:])', cache=True, nopython=True)
def _get_eig(H):
    return np.linalg.eig(H)

@jit('c16[:,:](c16, c16[:,:], c16[:,:])', parallel=True, nopython=True)
def _mat_diff(s, A, B):
    return s*(A - B)

class Constants:
    """Fundamental constants,
    including mass, hbar, e ... etc

    Attributes:
    m [float]: mass
    hbar [float]: Reduced Planck constant
    e [float]: Charge
    x0 [float]: Initial position
    L [float]: Length of the box
    N [int]: Number of spatial steps
    dx [float]: Space stepsize
    dt [float]: Time stepsize
    _scale [float]: multiply the potential by a certain amount.

    """

    def __init__(self):
        """
        Initialize the constants.
        """

        self.m    =1.           # Mass
        self.hbar =1.           # Reduced Planck constant
        self.e    =1.           # Charge

        self.x0 = -0.5          # Initial position
        self.L  = 1.            # The Length of the box
        self.N  = 512           # Number of spatial steps
        self.dx = self.L/self.N # Space stepsize
        self.dt = 0.00001       # Time stepsize

        self._scale=(128/self.N)*5e5

    def _get_constants(self):
        """
        Return constants.
        """

        return self.m, self.hbar, self.e, \
               self.L, self.N, self.dx, self.dt

class Wavefunction_1D(Constants):
    """Wavefunction class in 1D.

    Attributes:
    x [np.ndarray]: wavefunction in the position basis
    """

    def __init__(self, waveform):

        super().__init__()

        if callable(waveform):
            self.x = waveform(np.linspace(self.x0,
                                          (self.L + self.x0),
                                          self.N))
            self.x = self.x.astype(np.complex128)

        elif isinstance(waveform,np.ndarray):
            self.x = waveform
            self.x = self.x.astype(np.complex128)

    def normalize(self):
        """Normalize the wavefunction
        """

        try:
            self.x = self.x/np.sqrt(
                np.trapz(np.conj(self.x)*self.x,dx=self.dx))
            self.x = self.x.astype(np.complex128)
            #self.x = np.array(self.x, np.complex128)
        except FloatingPointError as E:
            print(E)

    def expectation_value(self, eigenvalues, eigenstates):
        """Find the expectation value of the wavefunction
        with respect to the eigenvalues and eigenstates
        of a Hermitian Operator
        """
        try:
            prob = np.abs(np.dot(self.x, eigenstates))**2
            if (np.max(prob) != 0.):
                prob = prob/np.sum(prob)
        except FloatingPointError as E:
            return 0.
            print(E)
        return np.sum(np.dot(np.real(eigenvalues), prob))

    def expected_momentum(self):
        """Find the momentum expectation value of the
        wavefunction
        """
        F = np.fft.fft(self.x)
        prob = np.abs(F)**2
        if (np.max(prob) != 0.):
            prob = prob/np.sum(prob)
        freq = np.fft.fftfreq(self.N, d=self.dx)
        p = 2*np.pi*freq*self.hbar/self.L
        return np.dot(p, prob)

    def set_to_momentum_eigenstate(self):
        """Set the wavefunction to an allowable
        momentum eigenstate.
        Return the momentum eigenvalue.

        The momentum eigenstates may not
        actually be defined for a particle in
        a box. See, for example, these questions:

        https://physics.stackexchange.com/q/66429
        [Question by JLA:
         physics.stackexchange.com/
         users/10964/jla]

        https://physics.stackexchange.com/q/45498
        [Question by Benji Remez:
         physics.stackexchange.com/
         users/12533/benji-remez]

         In any case, we Fourier transform the wavefunction, square
         it and find the most likely amplitude, and then inverse Fourier
         transform only this amplitude to obtain the momentum eigenstate.
        """
        F = np.fft.fft(self.x)
        prob = np.abs(F)**2
        if (np.max(prob) != 0.):
            prob = prob/np.sum(prob)
        freq = np.fft.fftfreq(self.N, d=self.dx)
        choice = np.random.choice(a=freq, size=1,
                                  p=prob, replace=False)
        k = choice[0]
        freq = np.array(
            [(0. if f != k else f) for f in freq])
        F = freq*F
        self.x = np.fft.ifft(F)
        self.normalize()
        p = 2*np.pi*k*self.hbar/self.L
        return p

    def set_to_eigenstate(self, eigenvalues, eigenstates):
        """Set the wavefunction to an eigenstate of
        any operator. Given the eigenvalues and eigenvectors
        of the operator, reset the wavefunction to the
        most probable eigenstate, then return the
        eigenvalue that corresponds to this eigenstate.
        """

        prob = np.abs(np.dot(self.x, eigenstates))**2
        if (np.max(prob) != 0.):
            prob = prob/np.sum(prob)

        a = [i for i in range(len(prob))]
        choice = np.random.choice(a=a, size=1, p=prob, replace=False)
        self.x = (eigenstates.T[[choice[0]]][0])

        self.normalize()

        return eigenvalues[choice[0]]


class Unitary_Operator_1D(Constants):
    """A unitary operator that dictates time evolution
    of the wavefunction.

    Attributes:
    U [np.ndarray]: Unitary time evolution matrix
    I [np.ndarray]: Identity matrix
    H [np.ndarray]: Hamiltonian operator which is the
       generator for time evolution.
    energy_eigenstates: Energy eigenstates of the
    [np.ndarray]        Hamiltonian
    energy_eigenvalues: The corresponding energy
    [np.ndarray]        to each eigenstate

    """

    def __init__(self, Potential):
        """Initialize the unitary operator.
        """

        # The unitary operator can be found by applying the Cranck-Nicholson
        # method. This method is outlined in great detail in exercise 9.8 of
        # Mark Newman's Computational Physics. Here is a link to a
        # page containing all problems in his book:
        # http://www-personal.umich.edu/~mejn/cp/exercises.html

        # Newman, M. (2013). Partial differential equations.
        # In Computational Physics, chapter 9.
        # CreateSpace Independent Publishing Platform.

        super().__init__()

        if isinstance(Potential, np.ndarray):
            V=Potential
            V = V.astype(np.complex128)

        elif callable(Potential):
            x=np.linspace(self.x0, (self.L + self.x0), self.N)
            V=np.array([Potential(xi) for xi in x], np.complex128)

        V *= self._scale

        #Get constants
        m, hbar, e, L, N, dx, dt = self._get_constants()

        #Initialize A and B matrices
        #A = np.zeros([N, N], np.complex128, order='F')
        #B = np.zeros([N, N], np.complex128, order='F')


        #Get the unitary operator
        self.U = _construct_U(V, m, hbar, N, dx, dt)
        self.U = self.U.astype(np.complex128, order="F")

        #The identity operator is what the unitary matrix
        #reduces to at time zero. Also,
        #since the wavefunction and all operators are
        #in the position basis, the identity matrix
        #is the position operator.
        self.I=np.identity(N, np.complex128)

        #Get the Hamiltonian from the unitary operator
        #and aquire the energy eigenstates.
        #self.Set_Energy_Eigenstates()

    def __call__(self, wavefunction):
        """Call this class
        on a wavefunction to time evolve it.
        """
        #wavefunction.x = np.matmul(self.U, wavefunction.x)
        wavefunction.x = _time_evolve_wavefunction(self.U, wavefunction.x)

    def Set_Hamiltonian(self):
        """Set the hamiltonian.
        """
        #The Hamiltonian H is the time derivative of U.


        hbar = np.dtype(np.complex128)
        dt = np.dtype(np.complex128)
        ihbar = 1.0j*self.hbar
        dt = self.dt
        self.H = _mat_diff((ihbar/dt), self.U, self.I)


    def Set_Energy_Eigenstates(self):
        """Set the eigenstates and energy eigenvalues.
        """

        self.Set_Hamiltonian()

        E, Eig = _get_eig(self.H)
        self.energy_eigenstates = Eig
        self.energy_eigenvalues = E
