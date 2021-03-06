###!/usr/bin/python
import sys, os, pwd, commands
import optparse, shlex, fnmatch, pprint
import time
from time import gmtime, strftime
import math
import re

eosExec = '/afs/cern.ch/project/eos/installation/0.3.84-aquamarine/bin/eos.select'

### parsing input options
def parseOptions():

    usage = ('usage: %prog [options]\n'
             + '%prog -h for help')
    parser = optparse.OptionParser(usage)

    # input options
    parser.add_option('-t', '--tag',    dest='TAG',    type='string',  default='',   help='tag to be appended to the resulting output dir, default is an empty string')
    parser.add_option('-q', '--queue',  dest='QUEUE',  type='string',  default='1nd',help='queue to be used with LSF batch, default is 1nd')
    parser.add_option('-n', '--nevts',  dest='NEVTS',  type=int,       default=100,  help='total number of events, applicable to runs with GEN stage, default is 100')
    parser.add_option('-e', '--evtsperjob',dest='EVTSPERJOB', type=int,default=-1,   help='number of events per job, if set to -1 it will set to a recommended value (GSD: 4events/1nh, RECO:8events/1nh), default is -1')
    parser.add_option('-c', '--cfg',    dest='CONFIGFILE', type='string', default='',help='CMSSW config template name, if empty string the deafult one will be used')
    parser.add_option('-p', '--partID', dest='PARTID', type='string',     default='', help='particle PDG ID, if empty string - run on all supported (11,12,13,14,15,16,22,111,211), default is empty string (all)')
    parser.add_option(  '', '--nPart',  dest='NPART',  type=int,   default=10,      help='number of particles of type PARTID to be generated per event, default is 10')
    parser.add_option(  '', '--thresholdMin',  dest='thresholdMin',  type=float, default=1.0,     help='min. threshold value')
    parser.add_option(  '', '--thresholdMax',  dest='thresholdMax',  type=float, default=35.0,    help='max. threshold value')
    parser.add_option(  '', '--gunType',   dest='gunType',   type='string', default='Pt',    help='Pt or E gun')
    parser.add_option('-l', '--local',  action='store_true', dest='LOCAL',  default=False, help='store output dir locally instead of at EOS CMG area, default is False.')
    parser.add_option('-y', '--dry-run',action='store_true', dest='DRYRUN', default=False, help='perform a dry run (no jobs are lauched).')
    parser.add_option(  '', '--eosArea',dest='eosArea',type='string', default='/eos/cms/store/cmst3/group/hgcal/CMG_studies/Production',help='path to the eos area where the output jobs will be staged out')
    parser.add_option('-d', '--datTier',dest='DTIER',  type='string', default='GSD',help='data tier to run: "GSD" (GEN-SIM-DIGI) or "RECO", default is "GSD"')
    parser.add_option('-i', '--inDir',  dest='inDir',  type='string', default='',   help='name of the previous stage dir (relative to the local submission or "eosArea"), to be used as the input for next stage, not applicable for GEN stage')

    # store options and arguments as global variables
    global opt, args
    (opt, args) = parser.parse_args()

    # sanity check for data tiers
    dataTiers = ['GSD', 'RECO', 'NTUP']
    if not opt.DTIER in dataTiers:
        parser.error('Data tier ' + opt.DTIER + ' is not supported. Exiting...')
        sys.exit()

    # make sure CMSSW is set up
    if not 'CMSSW_BASE' in os.environ:
        print 'ERROR: CMSSW does not seem to be set up. Exiting...'
        sys.exit()

    partGunTypes = ['Pt', 'E']
    if opt.gunType not in partGunTypes:
        parser.error('Particle gun type ' + opt.gunType + ' is not supported. Exiting...')
        sys.exit()

    # set the default config, if not specified in options
    if (opt.CONFIGFILE == ''):
        opt.CONFIGFILE = 'templates/partGun_'+opt.DTIER+'_template.py'

    # supported queues with the recommended number of events per hour (e.g. ~4events/1nh for GSD, ~8events/1nh for RECO) + sanity check
    eventsPerHour = {'GSD':4, 'RECO':8, 'NTUP':100}
    queues_evtsperjob = {'1nw':(7*24*eventsPerHour[opt.DTIER]), '2nd':(2*24*eventsPerHour[opt.DTIER]), '1nd':(1*24*eventsPerHour[opt.DTIER]), '8nh':(8*eventsPerHour[opt.DTIER]), '1nh':(1*eventsPerHour[opt.DTIER]), '8nm':(1)}
    if not opt.QUEUE in queues_evtsperjob.keys():
        parser.error('Queue ' + opt.QUEUE + ' is not supported. Exiting...')
        sys.exit()
    else:
        if opt.EVTSPERJOB==-1:
            opt.EVTSPERJOB = queues_evtsperjob[opt.QUEUE] # set the recommnded number of events per job, if requested

    # list of supported particles, check if requested partID is supported
    global particles
    particles = ['22', '111', '211', '11', '13', '15', '12', '14', '16']
    if not (opt.PARTID in particles or opt.PARTID==''):
        parser.error('Particle with ID ' + opt.PARTID + ' is not supported. Exiting...')
        sys.exit()
    if not (opt.PARTID==''):
        particles = []
        particles.append(opt.PARTID)

### processing the external os commands
def processCmd(cmd, quite = 0):
    #    print cmd
    status, output = commands.getstatusoutput(cmd)
    if (status !=0 and not quite):
        print 'Error in processing command:\n   ['+cmd+']'
        print 'Output:\n   ['+output+'] \n'
    return output

### print the setup
def printSetup(CMSSW_BASE, CMSSW_VERSION, SCRAM_ARCH, currentDir, outDir):
    global opt, particles
    print '--------------------'
    print '[Run parameters]'
    print '--------------------'
    print 'DATA TIER:  ', [opt.DTIER, 'GEN-SIM-DIGI'][int(opt.DTIER=='GSD')]
    print 'CMSSW BASE: ', CMSSW_BASE
    print 'CMSSW VER:  ', CMSSW_VERSION,'[', SCRAM_ARCH, ']'
    print 'CONFIGFILE: ', opt.CONFIGFILE
    print 'INPUTS:     ', [opt.inDir, 'Particle gun type: ' + opt.gunType + ', PDG ID '+str(opt.PARTID)+', '+str(opt.NPART)+' per event, ' + opt.gunType + ' threshold in ['+str(opt.thresholdMin)+','+str(opt.thresholdMax)+']'][int(opt.DTIER=='GSD')]
    print 'STORE AREA: ', [opt.eosArea, currentDir][int(opt.LOCAL)]
    print 'OUTPUT DIR: ', outDir
    print 'QUEUE:      ', opt.QUEUE
    print ['NUM. EVTS:   '+str(opt.NEVTS), ''][int(opt.DTIER!='GSD')]
    print '--------------------'

### prepare the list of input GSD files for RECO stage
def getInputFileList(inPath, inSubDir, local, pattern):
    inputList = []
    if (local):
        inputList = [f for f in os.listdir(inPath+'/'+inSubDir) if (os.path.isfile(os.path.join(inPath+'/'+inSubDir, f)) and (fnmatch.fnmatch(f, pattern)))]
    else:
        # this is a work-around, need to find a proper way to do it for EOS
        inputList = [f for f in processCmd(eosExec + ' ls ' + inPath+'/'+inSubDir+'/').split('\n') if ( (processCmd(eosExec + ' fileinfo ' + inPath+'/'+inSubDir+'/' + f).split(':')[0].lstrip() == 'File') and (fnmatch.fnmatch(f, pattern)))]
    return inputList

### submission of GSD/RECO production
def submitHGCalProduction():

    # parse the arguments and options
    global opt, args, particles
    parseOptions()

    # save working dir
    currentDir = os.getcwd()
    CMSSW_BASE = os.getenv('CMSSW_BASE')
    CMSSW_VERSION = os.getenv('CMSSW_VERSION')
    SCRAM_ARCH = os.getenv('SCRAM_ARCH')
    commonFileNamePrefix = 'partGun'
    partGunType = 'FlatRandom%sGunProducer' % opt.gunType

    # previous data tier
    previousDataTier = ''
    if (opt.DTIER == 'RECO'):
        previousDataTier = 'GSD'
    elif (opt.DTIER == 'NTUP'):
        previousDataTier = 'RECO'

    # prepare tag, prepare/check out dirs
    tag = opt.TAG+'_'+time.strftime("%Y%m%d")
    if (opt.DTIER == 'GSD'):
        outDir='partGun_'+tag
        if (not os.path.isdir(outDir)):
            processCmd('mkdir -p '+outDir+'/cfg/')
            processCmd('mkdir -p '+outDir+'/std/')
        else:
            print 'Directory '+outDir+' already exists. Exiting...'
            sys.exit()
    elif (opt.DTIER == 'RECO' or opt.DTIER == 'NTUP'):
        outDir=opt.inDir
        processCmd('mkdir -p '+outDir+'/cfg/')
        processCmd('mkdir -p '+outDir+'/std/')
    # prepare dir for GSD outputs locally or at EOS
    if (opt.LOCAL):
        processCmd('mkdir -p '+outDir+'/'+opt.DTIER+'/')
        recoInputPrefix = 'file:'+currentDir+'/'+outDir+'/'+previousDataTier+'/'
    else:
        processCmd(eosExec + ' mkdir -p '+opt.eosArea+'/'+outDir+'/'+opt.DTIER+'/');
        recoInputPrefix = 'root://eoscms.cern.ch/'+opt.eosArea+'/'+outDir+'/'+previousDataTier+'/'
    # determine number of jobs for GSD, in case of 'RECO'/'NTUP' only get the input GSD/RECO path
    if (opt.DTIER == 'GSD'):
        njobs = int(math.ceil(float(opt.NEVTS)/float(opt.EVTSPERJOB)))
    elif (opt.DTIER == 'RECO' or opt.DTIER == 'NTUP'):
        inPath = [opt.eosArea+'/'+opt.inDir, currentDir+'/'+opt.inDir][opt.LOCAL]

    # print out some info
    printSetup(CMSSW_BASE, CMSSW_VERSION, SCRAM_ARCH, currentDir, outDir)

    # submit all the jobs
    print '[Submitting jobs]'
    jobCount=0
    for particle in particles:
        nFilesPerJob = 0
        eventsPerPrevJob = 0
        # in case of 'RECO' or 'NTUP', get the input file list for given particle, determine number of jobs, get also basic GSD/RECO info
        if (opt.DTIER == 'RECO' or opt.DTIER == 'NTUP'):
            inputFilesList = getInputFileList(inPath, previousDataTier, opt.LOCAL, commonFileNamePrefix+'*_PDGid'+particle+'_*.root')
            if len(inputFilesList) == 0:
                continue
            # build regular expression for splitting
            regex = re.compile(ur"partGun_PDGid[0-9]*_x([0-9]*)_(E|Pt)([0-9]*[.]?[0-9]*)To([0-9]*[.]?[0-9]*)_.*\.root")
            matches = regex.match(inputFilesList[0])
            eventsPerPrevJob = int(matches.group(1))
            opt.gunType = matches.group(2)
            opt.thresholdMin = float(matches.group(3))
            opt.thresholdMax = float(matches.group(4))
            nFilesPerJob = max(int(math.floor(float(min(opt.EVTSPERJOB, len(inputFilesList)*eventsPerPrevJob))/float(eventsPerPrevJob))),1)
            njobs = int(math.ceil(float(len(inputFilesList))/float(nFilesPerJob)))

        for job in range(1,int(njobs)+1):
            print 'Submitting job '+str(job)+' out of '+str(njobs)+' for particle ID '+particle
            # prepare the out file and cfg file by replacing DUMMY entries according to input options
            basename = commonFileNamePrefix + '_PDGid'+particle+'_x'+str([nFilesPerJob * eventsPerPrevJob, opt.EVTSPERJOB][opt.DTIER=='GSD'])+'_' + opt.gunType+str(opt.thresholdMin)+'To'+str(opt.thresholdMax)+'_'+opt.DTIER+'_'+str(job)
            cfgfile = basename +'.py'
            outfile = basename +'.root'
            processCmd('cp '+opt.CONFIGFILE+' '+outDir+'/cfg/'+cfgfile)
            processCmd("sed -i 's~DUMMYFILENAME~"+outfile+"~g' "+outDir+'/cfg/'+cfgfile)
            processCmd("sed -i 's~DUMMYSEED~"+str(job)+"~g' "+outDir+'/cfg/'+cfgfile)
            if (opt.DTIER == 'GSD'):
                # prepare GEN-SIM-DIGI inputs
                nParticles = ','.join([particle for i in range(0,opt.NPART)])
                processCmd("sed -i 's~DUMMYEVTSPERJOB~"+str(opt.EVTSPERJOB)+"~g' "+outDir+'/cfg/'+cfgfile)
                processCmd("sed -i 's~DUMMYIDs~"+nParticles+"~g' "+outDir+'/cfg/'+cfgfile)
                processCmd("sed -i 's~DUMMYTHRESHMIN~"+str(opt.thresholdMin)+"~g' "+outDir+'/cfg/'+cfgfile)
                processCmd("sed -i 's~DUMMYTHRESHMAX~"+str(opt.thresholdMax)+"~g' "+outDir+'/cfg/'+cfgfile)
                processCmd("sed -i 's~GUNPRODUCERTYPE~"+str(partGunType)+"~g' "+outDir+'/cfg/'+cfgfile)
                processCmd("sed -i 's~MAXTHRESHSTRING~Max"+str(opt.gunType)+"~g' "+outDir+'/cfg/'+cfgfile)
                processCmd("sed -i 's~MINTHRESHSTRING~Min"+str(opt.gunType)+"~g' "+outDir+'/cfg/'+cfgfile)
            elif (opt.DTIER == 'RECO' or opt.DTIER == 'NTUP'):
                # prepare RECO inputs
                inputFilesListPerJob = inputFilesList[(job-1)*nFilesPerJob:(job)*nFilesPerJob]
                if len(inputFilesListPerJob)==0: continue
                inputFiles = '"' + '", "'.join([recoInputPrefix+str(f) for f in inputFilesListPerJob]) + '"'
                processCmd("sed -i 's~DUMMYINPUTFILELIST~"+inputFiles+"~g' "+outDir+'/cfg/'+cfgfile)
                processCmd("sed -i 's~DUMMYEVTSPERJOB~"+str(-1)+"~g' "+outDir+'/cfg/'+cfgfile)

            # submit job
            cmd = 'bsub -o '+outDir+'/std/'+basename +'.out -e '+outDir+'/std/'+basename +'.err -q '+opt.QUEUE+' -J '+basename+' "SubmitFileGSD.sh '+currentDir+' '+outDir+' '+cfgfile+' '+str(opt.LOCAL)+' '+CMSSW_VERSION+' '+CMSSW_BASE+' '+SCRAM_ARCH+' '+opt.eosArea+' '+opt.DTIER+'"'

            #TODO This could probably be better handled by a job array
            #Example: bsub -J "foo[1-3]" -oo "foo.%I.out" -eo "foo.%I.err" -q 8nm "sleep 1"
            #This and more at https://www.ibm.com/support/knowledgecenter/SSETD4_9.1.3/lsf_command_ref/bsub.man_top.1.html

            if(opt.DRYRUN):
                print 'Dry-run: ['+cmd+']'
            else:
                output = processCmd(cmd)
    #            while ('error' in output):
    #                time.sleep(1.0);
    #                output = processCmd(cmd)
    #                if ('error' not in output):
    #                    print 'Submitted after retry - job '+str(jobCount+1)


            jobCount += 1

    print '[Submitted '+str(jobCount)+' jobs]'

### run the submitHGCalProduction() as main
if __name__ == "__main__":
    submitHGCalProduction()
