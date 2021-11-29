from iqtools import *
from ROOT import *
import numpy as np
from amedata import *
from particle import *
from ring import Ring
import lisereader as lread
from inputparams import*
from scipy.optimize import minimize


class ImportData():
    def __init__(self, filename):
        self.master_filename = filename
        self.ring = Ring('ESR', 108.5)  # have to add more functionalities here

        self._read_masterfile()
        self._import()
        self._read_data()
        self._calculate()

    def _read_masterfile(self):
        # reads list filenames with experiment data. [:-1] to remove eol sequence.
        self.file_list = [file[:-1]
                          for file in open(self.master_filename).readlines()]
        # and for now:
        self.filename = self.file_list[0]

    def _import(self):
        # import ame from barion:
        self.ame = AMEData()
        self.ame.init_ame_db
        self.ame_data = self.ame.ame_table

        # import input params
        params_file = 'data/InputParameters.txt'
        input_params = InputParams(params_file)
        self.pdict = input_params.dict

        # Load LISE file
        lise_file = lread.LISEreader(input_params.lisefile)
        self.lise_data = lise_file.get_info_all()

    def _read_data(self):
        LFRAMES = 2**15
        NFRAMES = 2*4
        iq = TIQData(self.filename)
        iq.read_samples(LFRAMES*NFRAMES)

        # center frequency
        self.fcenter = iq.center
        
        # import xx:frequency, yy:time, zz:power
        xx, yy, zz = iq.get_spectrogram(lframes=LFRAMES, nframes=NFRAMES)
        self.ff = xx[0]  # frequency, index 0 as xx is 2d array
        self.pp = zz[0]/zz[0].max()  # normalized power

        # setting variables from tiq data
        self.h = TH1D('h', 'h', len(self.ff),
                      iq.center + self.ff[0], iq.center + self.ff[-1])
        for i in range(len(self.ff)):
            self.h.SetBinContent(i, self.pp[i])
        self.nbins = self.h.GetXaxis().GetNbins()
        self.frequence_min = self.h.GetXaxis().GetXmin()/1000+245
        self.frequence_max = self.h.GetXaxis().GetXmax()/1000+245
        self.y_max = self.h.GetMaximum()
        self.h.GetXaxis().SetLimits(self.frequence_min, self.frequence_max)

    def _calculate(self):
        # return yield data from lise
        yield_data = [element[5] for element in self.lise_data]
        self.yield_data_normalised = [element/max(yield_data) for element in yield_data]

        # return mass and moq from barion
        self.m = [AMEData.to_mev(Particle(lise[2], lise[3], self.ame, self.ring).get_ionic_mass_in_u())
                  for ame in self.ame_data for lise in self.lise_data if lise[0] == ame[6] and lise[1] == ame[5]]
        self.moq = [Particle(lise[2], lise[3], self.ame, self.ring).get_ionic_moq_in_u()
                    for ame in self.ame_data for lise in self.lise_data if lise[0] == ame[6] and lise[1] == ame[5]]

        # if reference particle, calculate variables with lise data
        for i, lise in enumerate(self.lise_data):
            if (str(lise[1])+lise[0] == self.pdict['ReferenceIsotope'] 
                and lise[4] == self.pdict['ReferenceIsotopeCharge']):
                self.aux = i
                self.moq_Rel = self.moq[i]
                self.calculate_ion_parameters(self.pdict['Brho'])

        # simulated relative and non-rel revolution frequencies
        self.SRRF = [1-1/self.pdict['GAMMAT']/self.pdict['GAMMAT']*(self.moq[k]-self.moq_Rel)/self.moq_Rel
                     for k in range(len(self.m))]
        self.SRF = [self.SRRF[k]*self.Frequence_Rel*self.pdict['Harmonic']
                    for k in range(len(self.m))]

        # print(f'before: {self.SRF}')
        # self.SRF=self.set_range_SRF_to_analyzer(self.SRF)
        # print(f'after: {self.SRF}')

        # Calculate new simulated frequency sample spectrum
        brho_correction = False
        if brho_correction == True:
            print(f"Brho initial: {self.pdict['Brho']}")
            self.BRhoCorrection()
            print(f"Brho final: {self.pdict['Brho']}")
            self.calculate_ion_parameters(self.pdict['Brho'])
            self.SRF = [element*self.Frequence_Rel *
                        self.pdict['Harmonic'] for element in self.SRRF]

    def tominimize(self, x):  # function to minimize (x=Brho); yup, it's big
        self.calculate_ion_parameters(x)
        SRF = self.Frequence_rel*self.pdict['Harmonic']*self.SRRF[self.aux]
        tominimize = abs((self.ff[self.pp.argmax()]+self.fcenter)-SRF)
        print(f'tominimize={tominimize}, BRho={x}')
        return tominimize

    # Performs minimization of f_data[IsochroIon]-f_sample[RefIon(Brho)]
    def BRhoCorrection(self):
        print(f"function to minimize before minimizing: {self.tominimize(self.pdict['Brho'])}")
        self.pdict['Brho'] = minimize(self.tominimize, [self.pdict['Brho']], method='Powell', bounds=[
                             (6.900, 6.910)], tol=1e-5).x[0]
        print(f"function minimized: {self.tominimize(self.pdict['Brho'])}")
        self.calculate_ion_parameters(self.pdict['Brho'])

    def calculate_ion_parameters(self, x):
        self.gamma = self.gamma(self.pdict['Brho'])
        self.beta = self.beta(self.gamma)
        self.velocity = self.velocity(self.beta)
        self.Frequence_Rel = self.frequence_rel(self.velocity)

    def set_range_SRF_to_analyzer(self, SRF):
        return SRF[(SRF > self.frequence_min)*(SRF < self.frequence_max)]

    def gamma(self, x):
        return np.sqrt(pow(x*self.pdict['ReferenceIsotopeCharge']*AMEData.CC/self.m[self.aux], 2)+1)

    def beta(self, gamma):
        return np.sqrt(gamma*gamma-1)/gamma

    def velocity(self, beta):
        return AMEData.CC*beta

    def frequence_rel(self, velocity):
        return velocity/self.ring.circumference

# main could be console user interface until gui is made


def main():
    # specified file is list of filenames
    # filename='data/245test'
    filename = 'data/410-j'
    test = ImportData(filename)


if __name__ == '__main__':
    main()
