#!/usr/bin/env python

# Script to build windows installer packages for LAMMPS
# (c) 2017,2018,2019,2020,2021,2022 Axel Kohlmeyer <akohlmey@gmail.com>

from __future__ import print_function
import sys,os,shutil,glob,re,subprocess,tarfile,gzip,time,inspect
try: from urllib.request import urlretrieve as geturl
except: from urllib import urlretrieve as geturl

try:
    import multiprocessing
    numcpus = multiprocessing.cpu_count()
except:
    numcpus = 1

# helper functions

def error(str=None):
    if not str: print(helpmsg)
    else: print(sys.argv[0],"ERROR:",str)
    sys.exit()

def getbool(arg,keyword):
    if arg in ['yes','Yes','Y','y','on','1','True','true']:
        return True
    elif arg in ['no','No','N','n','off','0','False','false']:
        return False
    else:
        error("Unknown %s option: %s" % (keyword,arg))

def fullpath(path):
    return os.path.abspath(os.path.expanduser(path))

def getexe(url,name):
    gzname = name + ".gz"
    geturl(url,gzname)
    with gzip.open(gzname,'rb') as gz_in:
      with open(name,'wb') as f_out:
        shutil.copyfileobj(gz_in,f_out)
    gz_in.close()
    f_out.close()
    os.remove(gzname)

def system(cmd):
    try:
        txt = subprocess.check_output(cmd,stderr=subprocess.STDOUT,shell=True)
    except subprocess.CalledProcessError as e:
        print("Command '%s' returned non-zero exit status" % e.cmd)
        error(e.output.decode('UTF-8'))
    return txt.decode('UTF-8')

def which(program):
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None

# record location and name of python script
homedir, exename = os.path.split(os.path.abspath(inspect.getsourcefile(lambda:0)))

# default settings help message and default settings

bitflag = '64'
parflag = 'no'
pythonflag  = False
guiflag = False
thrflag = 'omp'
revflag = 'stable'
verbose = False
gitdir  = os.path.join(homedir,"lammps")
adminflag = True
msixflag = False

helpmsg = """
Usage: python %s -b <bits> -j <cpus> -p <mpi> -t <thread> -y <yes|no> -r <rev> -v <yes|no> -g <folder> -a <yes|no>

Flags (all flags are optional, defaults listed below):
  -b : select Windows variant (default value: %s)
    -b 32       : build for 32-bit Windows
    -b 64       : build for 64-bit Windows
  -j : set number of CPUs for parallel make (default value: %d)
    -j <num>    : set to any reasonable number or 1 for serial make
  -p : select message passing parallel build (default value: %s)
    -p mpi      : build an MPI parallel version with MPICH2 v1.4.1p1
    -p ms       : build an MPI parallel version with MS-MPI SDK 10.1
    -p no       : build a serial version using MPI STUBS library
  -t : select thread support (default value: %s)
    -t omp      : build with threads via OpenMP enabled
    -t no       : build with thread support disabled
  -y : select python support (default value: %s)
    -y yes      : build with python included
    -y no       : build without python
  -u : select whether to include the LAMMPS GUI (default value: %s)
    -u yes      : build includes LAMMPS GUI
    -u no       : build does not include LAMMPS GUI
  -r : select LAMMPS source revision to build (default value: %s)
    -r stable   : download and build the latest stable LAMMPS version
    -r release  : download and build the latest patch release LAMMPS version
    -r develop  : download and build the latest development snapshot
    -r maintenance  : download and build the latest maintenance snapshot
    -r patch_<date> : download and build a specific patch release
    -r maintenance_<date> : download and build a specific maintenance branch
    -r <sha256> : download and build a specific snapshot version
  -v : select output verbosity
    -v yes      : print progress messages and output of make commands
    -v no       : print only progress messages
  -g : select folder with git checkout of LAMMPS sources
    -g <folder> : use LAMMPS checkout in <folder>  (default value: %s)
  -a : select admin level installation (default value: yes)
    -a yes      : the created installer requires to be run at admin level
                  and LAMMPS is installed to be accessible by all users
    -a no       : the created installer runs without admin privilege and
                  LAMMPS is installed into the current user's appdata folder
    -a msix     : same as "no" but adjust for creating an MSIX package

Example:
  python %s -r release -t omp -p mpi
""" % (exename,bitflag,numcpus,parflag,thrflag,pythonflag,guiflag,revflag,gitdir,exename)

# parse arguments

argv = sys.argv
argc = len(argv)
i = 1

while i < argc:
    if i+1 >= argc:
        print("\nMissing argument to flag:",argv[i])
        error()
    if argv[i] == '-b':
        bitflag = argv[i+1]
    elif argv[i] == '-j':
        numcpus = int(argv[i+1])
    elif argv[i] == '-p':
        parflag = argv[i+1]
    elif argv[i] == '-t':
        thrflag = argv[i+1]
    elif argv[i] == '-y':
        pythonflag = getbool(argv[i+1],"python")
    elif argv[i] == '-u':
        guiflag = getbool(argv[i+1],"gui")
    elif argv[i] == '-r':
        revflag = argv[i+1]
    elif argv[i] == '-v':
        verbose = getbool(argv[i+1],"verbose")
    elif argv[i] == '-a':
        if argv[i+1] in ['msix','MSIX']:
            adminflag = False
            msixflag = True
        else:
            msixflag = False
            adminflag = getbool(argv[i+1],"admin")
    elif argv[i] == '-g':
        gitdir = fullpath(argv[i+1])
    else:
        print("\nUnknown flag:",argv[i])
        error()
    i+=2

# checks
if bitflag != '32' and bitflag != '64':
    error("Unsupported bitness flag %s" % bitflag)
if parflag != 'no' and parflag != 'mpi' and parflag != 'ms':
    error("Unsupported parallel flag %s" % parflag)
if thrflag != 'no' and thrflag != 'omp':
    error("Unsupported threading flag %s" % thrflag)
if pythonflag and guiflag:
    error("May only include either Python or LAMMPS GUI")

# test for valid revision name format: branch names, release tags, or commit hashes
rev1 = re.compile("^(stable|release|develop|maintenance)$")
rev2 = re.compile(r"^(patch|stable)_\d+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\d{4}$")
rev3 = re.compile(r"^[a-f0-9]{40}$")
if not rev1.match(revflag) and not rev2.match(revflag) and not rev3.match(revflag):
    error("Unsupported revision flag %s" % revflag)

# create working directory
if adminflag:
    builddir = os.path.join(fullpath('.'),"tmp-%s-%s-%s-%s" % (bitflag,parflag,thrflag,revflag))
else:
    if pythonflag:
        builddir = os.path.join(fullpath('.'),"tmp-%s-%s-%s-%s-python" % (bitflag,parflag,thrflag,revflag))
    elif guiflag:
        builddir = os.path.join(fullpath('.'),"tmp-%s-%s-%s-%s-gui" % (bitflag,parflag,thrflag,revflag))
    elif msixflag:
        builddir = os.path.join(fullpath('.'),"tmp-%s-%s-%s-%s-msix" % (bitflag,parflag,thrflag,revflag))
    else:
        builddir = os.path.join(fullpath('.'),"tmp-%s-%s-%s-%s-noadmin" % (bitflag,parflag,thrflag,revflag))
shutil.rmtree(builddir,True)
try:
    os.mkdir(builddir)
except:
    error("Cannot create temporary build folder: %s" % builddir)

# check for prerequisites and set up build environment
if bitflag == '32':
    cc_cmd = which('i686-w64-mingw32-gcc')
    cxx_cmd = which('i686-w64-mingw32-g++')
    fc_cmd = which('i686-w64-mingw32-gfortran')
    ar_cmd = which('i686-w64-mingw32-ar')
    size_cmd = which('i686-w64-mingw32-size')
    nsis_cmd = which('makensis')
    lmp_size = 'smallsmall'
else:
    cc_cmd = which('x86_64-w64-mingw32-gcc')
    cxx_cmd = which('x86_64-w64-mingw32-g++')
    fc_cmd = which('x86_64-w64-mingw32-gfortran')
    ar_cmd = which('x86_64-w64-mingw32-ar')
    size_cmd = which('x86_64-w64-mingw32-size')
    nsis_cmd = which('makensis')
    lmp_size = 'smallbig'

print("""
Settings: building LAMMPS revision %s for %s-bit Windows
Message passing  : %s
Multi-threading  : %s
Home folder      : %s
Source folder    : %s
Build folder     : %s
C compiler       : %s
C++ compiler     : %s
Fortran compiler : %s
Library archiver : %s
""" % (revflag,bitflag,parflag,thrflag,homedir,gitdir,builddir,cc_cmd,cxx_cmd,fc_cmd,ar_cmd))

# create/update git checkout
if not os.path.exists(gitdir):
    txt = system("git clone https://github.com/lammps/lammps.git %s" % gitdir)
    if verbose: print(txt)

os.chdir(gitdir)
txt = system("git fetch origin")
if verbose: print(txt)
txt = system("git checkout %s" % revflag)
if verbose: print(txt)
if revflag == "develop" or revflag == "stable" or revflag == "release" or revflag == "maintenance":
    txt = system("git pull")
    if verbose: print(txt)

# switch to build folder
os.chdir(builddir)

# download what is not automatically downloaded by CMake
print("Downloading third party tools")
url='http://download.lammps.org/thirdparty'
print("FFMpeg")
getexe("%s/ffmpeg-win%s.exe.gz" % (url,bitflag),"ffmpeg.exe")
print("gzip")
getexe("%s/gzip.exe.gz" % url,"gzip.exe")

if parflag == "mpi" or parflag == "ms":
    mpiflag = "on"
else:
    mpiflag = "off"

if thrflag == "omp":
    ompflag = "on"
else:
    ompflag = "off"

print("Configuring build with CMake")
cmd = "mingw%s-cmake -D CMAKE_BUILD_TYPE=Release" % bitflag
cmd += " -D ADD_PKG_CONFIG_PATH=%s/mingw%s-pkgconfig" % (homedir,bitflag)
cmd += " -C %s/mingw%s-pkgconfig/addpkg.cmake" % (homedir,bitflag)
cmd += " -C %s/cmake/presets/mingw-cross.cmake -S %s/cmake" % (gitdir,gitdir)
if bitflag == '64':
  cmd += " -C %s/cmake/presets/kokkos-openmp.cmake" % gitdir
cmd += " -DBUILD_SHARED_LIBS=on -DBUILD_MPI=%s -DBUILD_OMP=%s" % (mpiflag,ompflag)
if parflag == 'ms':
  cmd += " -DUSE_MSMPI=on"
if guiflag:
  cmd += " -DBUILD_LAMMPS_GUI=on -DQt5_DIR=/usr/x86_64-w64-mingw32/sys-root/mingw/lib/cmake/Qt5"
cmd += " -DWITH_GZIP=on -DWITH_FFMPEG=on -DLAMMPS_EXCEPTIONS=on"
cmd += " -DINTEL_LRT_MODE=c++11 -DBUILD_LAMMPS_SHELL=on"
cmd += " -DCMAKE_CXX_COMPILER_LAUNCHER=ccache"
cmd += " -DPKG_PLUGIN=yes -DPKG_PLUMED=yes"
if pythonflag: cmd += " -DPKG_PYTHON=yes"

print("Running: ",cmd)
txt = system(cmd)
if verbose: print(txt)

# create qt.conf file
if guiflag:
  with open("qt.conf", "w") as qtconf:
    qtconf.write("[Paths]\nPlugins = ../qt5plugins\n")
    qtconf.close()

print("Compiling")
system("cmake --build . --parallel 8")
print("Done")

print("Configuring demo plugin build with CMake")
cmd = "mingw%s-cmake -D CMAKE_BUILD_TYPE=Release" % bitflag
cmd += " -S %s/examples/plugins -B plugins" % gitdir
cmd += " -DBUILD_SHARED_LIBS=on -DBUILD_MPI=%s -DBUILD_OMP=%s" % (mpiflag,ompflag)
if parflag == 'ms': cmd += " -DUSE_MSMPI=on"
cmd += " -DCMAKE_CXX_COMPILER_LAUNCHER=ccache"

print("Running: ",cmd)
txt = system(cmd)
if verbose: print(txt)

print("Compiling")
txt = system("cmake --build plugins")
if verbose: print(txt)
print("Done")

if not adminflag and not pythonflag and not msixflag and not guiflag:
  print("Configuring pace plugin build with CMake")
  cmd = "mingw%s-cmake -D CMAKE_BUILD_TYPE=Release" % bitflag
  cmd += " -S %s/examples/PACKAGES/pace/plugin -B paceplugin" % gitdir
  cmd += " -DBUILD_SHARED_LIBS=on -DBUILD_MPI=%s -DBUILD_OMP=%s" % (mpiflag,ompflag)
  cmd += " -DCMAKE_CXX_COMPILER_LAUNCHER=ccache -DLAMMPS_SOURCE_DIR=%s/src" % gitdir
  if parflag == 'ms': cmd += " -DUSE_MSMPI=on"

  print("Running: ",cmd)
  txt = system(cmd)
  if verbose: print(txt)
  print("Done")

  print("Compiling and building installer")
  txt = system("cmake --build paceplugin --target package")
  if verbose: print(txt)
  for exe in glob.glob('paceplugin/LAMMPS*plugin*.exe'):
    shutil.move(exe,os.path.join('..',os.path.basename(exe)))
  print("Done")

  print("Cloning lammps-plugin package")
  txt = system("git clone -b %s --depth 1 git@github.com:lammps/lammps-plugins.git" % revflag)
  if verbose: print(txt)
  print("Configuring LAMMPS plugin collection build with CMake")
  cmd = "mingw%s-cmake -D CMAKE_BUILD_TYPE=Release" % bitflag
  cmd += " -S lammps-plugins -B build_plugins"
  cmd += " -DBUILD_SHARED_LIBS=on -DBUILD_MPI=%s -DBUILD_OMP=%s" % (mpiflag,ompflag)
  cmd += " -DCMAKE_CXX_COMPILER_LAUNCHER=ccache -DLAMMPS_SOURCE_DIR=%s/src" % gitdir
  if parflag == 'ms': cmd += " -DUSE_MSMPI=on"

  print("Running: ",cmd)
  txt = system(cmd)
  if verbose: print(txt)
  print("Done")

  print("Compiling and building installer")
  txt = system("cmake --build build_plugins --target package")
  if verbose: print(txt)
  for exe in glob.glob('build_plugins/LAMMPS*plugin*.exe'):
    shutil.move(exe,os.path.join('..',os.path.basename(exe)))
  print("Done")

print("Building PDF manual")
os.chdir(os.path.join(gitdir,"doc"))
txt = system("make pdf")
if verbose: print(txt)
shutil.move("Manual.pdf",os.path.join(builddir,"LAMMPS-Manual.pdf"))
print("Done")

# switch back to build folder and copy/process files for inclusion in installer
print("Collect and convert files for the Installer package")
os.chdir(builddir)
shutil.copytree(os.path.join(gitdir,"examples"),os.path.join(builddir,"examples"),symlinks=False)
shutil.copytree(os.path.join(gitdir,"bench"),os.path.join(builddir,"bench"),symlinks=False)
shutil.copytree(os.path.join(gitdir,"tools"),os.path.join(builddir,"tools"),symlinks=False)
shutil.copytree(os.path.join(gitdir,"python","lammps"),os.path.join(builddir,"python","lammps"),symlinks=False)
shutil.copytree(os.path.join(gitdir,"potentials"),os.path.join(builddir,"potentials"),symlinks=False)
shutil.copy(os.path.join(gitdir,"README"),os.path.join(builddir,"README.txt"))
shutil.copy(os.path.join(gitdir,"LICENSE"),os.path.join(builddir,"LICENSE.txt"))
shutil.copy(os.path.join(gitdir,"doc","src","PDF","colvars-refman-lammps.pdf"),os.path.join(builddir,"Colvars-Manual.pdf"))
shutil.copy(os.path.join(gitdir,"tools","createatoms","Manual.pdf"),os.path.join(builddir,"CreateAtoms-Manual.pdf"))
shutil.copy(os.path.join(gitdir,"doc","src","PDF","kspace.pdf"),os.path.join(builddir,"Kspace-Extra-Info.pdf"))
shutil.copy(os.path.join(gitdir,"doc","src","PDF","pair_gayberne_extra.pdf"),os.path.join(builddir,"PairGayBerne-Manual.pdf"))
shutil.copy(os.path.join(gitdir,"doc","src","PDF","pair_resquared_extra.pdf"),os.path.join(builddir,"PairReSquared-Manual.pdf"))
shutil.copy(os.path.join(gitdir,"doc","src","PDF","PDLammps_overview.pdf"),os.path.join(builddir,"PDLAMMPS-Overview.pdf"))
shutil.copy(os.path.join(gitdir,"doc","src","PDF","PDLammps_EPS.pdf"),os.path.join(builddir,"PDLAMMPS-EPS.pdf"))
shutil.copy(os.path.join(gitdir,"doc","src","PDF","PDLammps_VES.pdf"),os.path.join(builddir,"PDLAMMPS-VES.pdf"))
shutil.copy(os.path.join(gitdir,"doc","src","PDF","SPH_LAMMPS_userguide.pdf"),os.path.join(builddir,"SPH-Manual.pdf"))
shutil.copy(os.path.join(gitdir,"doc","src","PDF","MACHDYN_LAMMPS_userguide.pdf"),os.path.join(builddir,"MACHDYN-Manual.pdf"))
shutil.copy(os.path.join(gitdir,"doc","src","PDF","CG-DNA.pdf"),os.path.join(builddir,"CG-DNA-Manual.pdf"))

# prune outdated inputs, too large files, or examples of packages we don't bundle
for d in ['accelerate','kim','mscg','PACKAGES/quip','PACKAGES/vtk']:
    shutil.rmtree(os.path.join("examples",d),True)
for d in ['FERMI','KEPLER']:
    shutil.rmtree(os.path.join("bench",d),True)
shutil.rmtree("tools/msi2lmp/test",True)
if os.path.exists("potentials/C_10_10.mesocnt"):
    os.remove("potentials/C_10_10.mesocnt")
if os.path.exists("potentials/TABTP_10_10.mesont"):
    os.remove("potentials/TABTP_10_10.mesont")
if os.path.exists("examples/PACKAGES/mesont/C_10_10.mesocnt"):
    os.remove("examples/PACKAGES/mesont/C_10_10.mesocnt")
if os.path.exists("examples/PACKAGES/mesont/TABTP_10_10.mesont"):
    os.remove("examples/PACKAGES/mesont/TABTP_10_10.mesont")

# convert text files to CR-LF conventions
txt = system("unix2dos LICENSE.txt README.txt tools/msi2lmp/README")
if verbose: print(txt)
txt = system("find bench examples potentials python tools/msi2lmp/frc_files -type f -print | xargs unix2dos")
if verbose: print(txt)
# mass rename README to README.txt
txt = system('for f in $(find tools bench examples potentials python -name README -print); do  mv -v $f $f.txt; done')
if verbose: print(txt)
# mass rename in.<name> to in.<name>.lmp
txt = system('for f in $(find bench examples -name in.\* -print); do  mv -v $f $f.lmp; done')
if verbose: print(txt)
print("Done")

print("Configuring and building installer")
os.chdir(builddir)
if pythonflag:
    nsisfile = os.path.join(homedir,"installer","lammps-python.nsis")
elif guiflag:
    nsisfile = os.path.join(homedir,"installer","lammps-gui.nsis")
elif adminflag:
    nsisfile = os.path.join(homedir,"installer","lammps-admin.nsis")
elif parflag == 'ms':
    nsisfile = os.path.join(homedir,"installer","lammps-msmpi.nsis")
else:
    if msixflag:
        nsisfile = os.path.join(homedir,"installer","lammps-msix.nsis")
    else:
        nsisfile = os.path.join(homedir,"installer","lammps-noadmin.nsis")

shutil.copy(nsisfile,os.path.join(builddir,"lammps.nsis"))
shutil.copy(os.path.join(homedir,"installer","FileAssociation.nsh"),os.path.join(builddir,"FileAssociation.nsh"))
shutil.copy(os.path.join(homedir,"installer","lammps.ico"),os.path.join(builddir,"lammps.ico"))
shutil.copy(os.path.join(homedir,"installer","lammps-text-logo-wide.bmp"),os.path.join(builddir,"lammps-text-logo-wide.bmp"))

# define version flag of the installer:
# - use current timestamp, when pulling from develop (for daily builds)
# - parse version from src/version.h when pulling from stable, release, or specific tag
# - otherwise use revflag, i.e. the commit hash
version = revflag
if revflag == 'stable' or revflag == 'release' or rev2.match(revflag):
  with open(os.path.join(gitdir,"src","version.h"),'r') as v_file:
    verexp = re.compile(r'^.*"(\w+) (\w+) (\w+)".*$')
    vertxt = v_file.readline()
    verseq = verexp.match(vertxt).groups()
    version = "".join(verseq)
elif revflag == 'develop' or revflag == 'maintenance':
    version = time.strftime('%Y-%m-%d')

if bitflag == '32':
    mingwdir = '/usr/i686-w64-mingw32/sys-root/mingw/bin/'
elif bitflag == '64':
    mingwdir = '/usr/x86_64-w64-mingw32/sys-root/mingw/bin/'

if parflag == 'mpi':
    txt = system("makensis -DMINGW=%s -DVERSION=%s-MPI -DBIT=%s -DLMPREV=%s lammps.nsis" % (mingwdir,version,bitflag,revflag))
    if verbose: print(txt)
elif parflag == 'ms':
    txt = system("makensis -DMINGW=%s -DVERSION=%s-MSMPI -DBIT=%s -DLMPREV=%s lammps.nsis" % (mingwdir,version,bitflag,revflag))
    if verbose: print(txt)
else:
    txt = system("makensis -DMINGW=%s -DVERSION=%s -DBIT=%s -DLMPREV=%s lammps.nsis" % (mingwdir,version,bitflag,revflag))
    if verbose: print(txt)

# clean up after successful build
os.chdir('..')

print("Cleaning up...")
shutil.rmtree(builddir,True)
print("Done.")

