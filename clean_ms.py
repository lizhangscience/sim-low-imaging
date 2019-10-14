import argparse
import logging
import pprint
import sys
import time

import astropy.units as u
import matplotlib.pyplot as plt
import numpy
from astropy.coordinates import SkyCoord, EarthLocation

from data_models.polarisation import ReceptorFrame
from processing_components.griddata.kernels import create_awterm_convolutionfunction
from processing_components.image.operations import qa_image, export_image_to_fits, show_image
from processing_components.imaging.base import advise_wide_field, create_image_from_visibility
from processing_components.visibility.base import create_blockvisibility_from_ms, vis_summary
from processing_components.visibility.coalesce import convert_blockvisibility_to_visibility, coalesce_visibility
from workflows.arlexecute.imaging.imaging_arlexecute import weight_list_arlexecute_workflow, \
    invert_list_arlexecute_workflow, sum_invert_results_arlexecute
from processing_components.griddata.convolution_functions import convert_convolutionfunction_to_image
from workflows.arlexecute.pipelines.pipeline_arlexecute import continuum_imaging_list_arlexecute_workflow
from wrappers.arlexecute.execution_support.arlexecute import arlexecute
from wrappers.arlexecute.execution_support.dask_init import get_dask_Client

pp = pprint.PrettyPrinter()

log = logging.getLogger()
log.setLevel(logging.INFO)
log.addHandler(logging.StreamHandler(sys.stdout))
mpl_logger = logging.getLogger("matplotlib")
mpl_logger.setLevel(logging.WARNING)

import matplotlib as mpl

mpl.use('Agg')

if __name__ == "__main__":
    
    # 116G	/mnt/storage-ssd/tim/data/GLEAM_A-team_EoR0_0.270_dB.ms
    # 116G	/mnt/storage-ssd/tim/data/GLEAM_A-team_EoR0_no_errors.ms
    msnames = ['/mnt/storage-ssd/tim/data/GLEAM_A-team_EoR0_0.270_dB.ms',
               '/mnt/storage-ssd/tim/data/GLEAM_A-team_EoR0_no_errors.ms']
    
    msnames = ['/alaska/tim/Code/sim-low-imaging/data/GLEAM_A-team_EoR0_0.270_dB.ms',
               '/alaska/tim/Code/sim-low-imaging/data/GLEAM_A-team_EoR0_no_errors.ms']
    
    # 7.8G	/mnt/storage-ssd/tim/data/EoR0_20deg_24.MS
    # 31G	/mnt/storage-ssd/tim/data/EoR0_20deg_96.MS
    # 62G	/mnt/storage-ssd/tim/data/EoR0_20deg_192.MS
    # 116G	/mnt/storage-ssd/tim/data/EoR0_20deg_360.MS
    # 155G	/mnt/storage-ssd/tim/data/EoR0_20deg_480.MS
    # 194G	/mnt/storage-ssd/tim/data/EoR0_20deg_600.MS
    # 232G	/mnt/storage-ssd/tim/data/EoR0_20deg_720.MS
    msname_times = [
        '/alaska/tim/Code/sim-low-imaging/data/EoR0_20deg_24.MS',
        '/alaska/tim/Code/sim-low-imaging/data/EoR0_20deg_96.MS',
        '/alaska/tim/Code/sim-low-imaging/data/EoR0_20deg_192.MS',
        '/alaska/tim/Code/sim-low-imaging/data/EoR0_20deg_480.MS',
        '/alaska/tim/Code/sim-low-imaging/data/EoR0_20deg_600.MS',
        '/alaska/tim/Code/sim-low-imaging/data/EoR0_20deg_360.MS',
        '/alaska/tim/Code/sim-low-imaging/data/EoR0_20deg_720.MS']
    
    start_epoch = time.asctime()
    print("\nSKA LOW imaging using ARL\nStarted at %s\n" % start_epoch)
    
    ########################################################################################################################
    
    parser = argparse.ArgumentParser(description='SKA LOW imaging using ARL')
    parser.add_argument('--context', type=str, default='2d', help='Imaging context')
    parser.add_argument('--mode', type=str, default='pipeline', help='Imaging mode')
    parser.add_argument('--msname', type=str, default='../data/EoR0_20deg_24.MS',
                        help='MS to process')
    parser.add_argument('--local_directory', type=str, default='dask-workspace',
                        help='Local directory for Dask files')
    
    parser.add_argument('--channels', type=int, nargs=2, default=[0, 160], help='Channels to process')
    parser.add_argument('--ngroup', type=int, default=4,
                        help='Number of channels in each BlockVisibility')
    parser.add_argument('--single', type=str, default='False', help='Use a single channel')
    parser.add_argument('--nmoment', type=int, default=1, help='Number of spectral moments')
    
    parser.add_argument('--time_coal', type=float, default=0.0, help='Coalesce time')
    parser.add_argument('--frequency_coal', type=float, default=0.0, help='Coalesce frequency')
    
    parser.add_argument('--npixel', type=int, default=None, help='Number of pixels')
    parser.add_argument('--fov', type=float, default=1.0, help='Field of view in primary beams')
    parser.add_argument('--cellsize', type=float, default=None, help='Cellsize in radians')
    
    parser.add_argument('--wstep', type=float, default=None, help='FStep in w')
    parser.add_argument('--nwplanes', type=int, default=None, help='Number of wplanes')
    parser.add_argument('--nwslabs', type=int, default=None, help='Number of w slabs')
    parser.add_argument('--amplitude_loss', type=float, default=0.02, help='Amplitude loss due to w sampling')
    parser.add_argument('--facets', type=int, default=1, help='Number of facets in imaging')
    parser.add_argument('--oversampling', type=int, default=16, help='Oversampling in w projection kernel')

    parser.add_argument('--weighting', type=str, default='natural', help='Type of weighting')
    
    parser.add_argument('--nmajor', type=int, default=1, help='Number of major cycles')
    parser.add_argument('--niter', type=int, default=1, help='Number of iterations per major cycle')
    parser.add_argument('--fractional_threshold', type=float, default=0.2,
                        help='Fractional threshold to terminate major cycle')
    parser.add_argument('--threshold', type=float, default=0.01, help='Absolute threshold to terminate')
    parser.add_argument('--window_shape', type=str, default=None, help='Window shape')
    parser.add_argument('--window_edge', type=int, default=None, help='Window edge')
    parser.add_argument('--restore_facets', type=int, default=1, help='Number of facets in restore')
    parser.add_argument('--deconvolve_facets', type=int, default=1, help='Number of facets in deconvolution')
    parser.add_argument('--deconvolve_overlap', type=int, default=128, help='overlap in deconvolution')
    parser.add_argument('--deconvolve_taper', type=str, default='tukey', help='Number of facets in deconvolution')
    
    parser.add_argument('--serial', type=str, default='False', help='Use serial processing?')
    parser.add_argument('--nworkers', type=int, default=4, help='Number of workers')
    parser.add_argument('--threads_per_worker', type=int, default=4, help='Number of threads per worker')
    parser.add_argument('--memory', type=int, default=64, help='Memory of each worker')
    
    parser.add_argument('--use_serial_invert', type=str, default='False', help='Use serial invert?')
    parser.add_argument('--use_serial_predict', type=str, default='False', help='Use serial invert?')
    parser.add_argument('--plot', type=str, default='False', help='Plot data?')
    
    args = parser.parse_args()
    
    pp.pprint(vars(args))
    
    target_ms = args.msname
    print("Target MS is %s" % target_ms)
    
    ochannels = numpy.arange(args.channels[0], args.channels[1] + 1)
    nmoment = args.nmoment
    print(ochannels)
    ngroup = args.ngroup
    weighting = args.weighting
    nwplanes = args.nwplanes
    nwslabs = args.nwslabs
    npixel = args.npixel
    cellsize = args.cellsize
    mode = args.mode
    fov = args.fov
    facets = args.facets
    wstep = args.wstep
    context = args.context
    use_serial_invert = args.use_serial_invert == "True"
    use_serial_predict = args.use_serial_predict == "True"
    serial = args.serial == "True"
    plot = args.plot == "True"
    single = args.single == "True"
    nworkers = args.nworkers
    threads_per_worker = args.threads_per_worker
    memory = args.memory
    time_coal = args.time_coal
    frequency_coal = args.frequency_coal
    local_directory = args.local_directory
    window_edge = args.window_edge
    window_shape = args.window_shape
    dela = args.amplitude_loss
    
    ####################################################################################################################
    
    print("\nSetup of processing mode")
    if serial:
        print("Will use serial processing")
        use_serial_invert = True
        use_serial_predict = True
        arlexecute.set_client(use_dask=False)
        print(arlexecute.client)
    else:
        print("Will use dask processing")
        if nworkers > 0:
            client = get_dask_Client(n_workers=nworkers, memory_limit=memory * 1024 * 1024 * 1024,
                                     local_dir=local_directory, threads_per_worker=threads_per_worker)
            arlexecute.set_client(client=client)
        else:
            client = get_dask_Client()
            arlexecute.set_client(client=client)
        
        print(arlexecute.client)
        if use_serial_invert:
            print("Will use serial invert")
        else:
            print("Will use distributed invert")
        if use_serial_predict:
            print("Will use serial predict")
        else:
            print("Will use distributed predict")

    ####################################################################################################################
    
    # Read an MS and convert to Visibility format
    print("\nSetup of visibility ingest")
    
    
    def read_convert(ms, ch):
        start = time.time()
        bvis = create_blockvisibility_from_ms(ms, start_chan=ch[0], end_chan=ch[1])[0]
        # The following are not set in the MSes
        bvis.configuration.location = EarthLocation(lon="116.76444824", lat="-26.824722084", height=300.0)
        bvis.configuration.frame = ""
        bvis.configuration.receptor_frame = ReceptorFrame("linear")
        bvis.configuration.data['diameter'][...] = 35.0
        
        if time_coal > 0.0 or frequency_coal > 0.0:
            vis = coalesce_visibility(bvis, time_coal=time_coal, frequency_coal=frequency_coal)
            print("Time to read and convert %s, channels %d to %d = %.1f s" % (ms, ch[0], ch[1], time.time() - start))
            print('Size of visibility before compression %s, after %s' % (vis_summary(bvis), vis_summary(vis)))
        else:
            vis = convert_blockvisibility_to_visibility(bvis)
            print("Time to read and convert %s, channels %d to %d = %.1f s" % (ms, ch[0], ch[1], time.time() - start))
            print('Size of visibility before conversion %s, after %s' % (vis_summary(bvis), vis_summary(vis)))
        del bvis
        return vis
    
    
    channels = []
    for i in range(0, len(ochannels) - 1, ngroup):
        channels.append([ochannels[i], ochannels[i + ngroup - 1]])
    print(channels)
    
    if single:
        channels = [channels[0]]
        print("Will read single range of channels %s" % channels)
    
    vis_list = [arlexecute.execute(read_convert)(target_ms, group_chan) for group_chan in channels]
    vis_list = arlexecute.persist(vis_list)
    
    ####################################################################################################################
    
    print("\nSetup of images")
    phasecentre = SkyCoord(ra=0.0 * u.deg, dec=-27.0 * u.deg)
    
    advice = [arlexecute.execute(advise_wide_field)(v, guard_band_image=fov, delA=dela, verbose=(iv == 0))
              for iv, v in enumerate(vis_list)]
    advice = arlexecute.compute(advice, sync=True)
    
    if npixel is None:
        npixel = advice[0]['npixels_min']
    
    if wstep is None:
        wstep = 1.1 * advice[0]['wstep']
    
    if nwplanes is None:
        nwplanes = advice[0]['wprojection_planes']
    
    if cellsize is None:
        cellsize = advice[-1]['cellsize']
    
    cellsize = 1.7578125 * numpy.pi / (180.0 * 3600.0)
    
    print('Image shape is %d by %d pixels' % (npixel, npixel))
    
    ####################################################################################################################
    
    print("\nSetup of wide field imaging")
    vis_slices = 1
    actual_context = '2d'
    support = 1
    if context == 'wprojection':
        # w projection
        vis_slices = 1
        support = advice[0]['nwpixels']
        actual_context = '2d'
        print("Will do w projection, %d planes, support %d, step %.1f" %
              (nwplanes, support, wstep))
    
    elif context == 'wstack':
        # w stacking
        print("Will do w stack, %d planes, step %.1f" % (nwplanes, wstep))
        actual_context = 'wstack'
    
    elif context == 'wprojectwstack':
        # Hybrid w projection/wstack
        nwplanes = int(1.5 * nwplanes) // nwslabs
        support = int(1.5 * advice[0]['nwpixels'] / nwslabs)
        support = max(15, int(3.0 * advice[0]['nwpixels'] / nwslabs))
        support -= support % 2
        vis_slices = nwslabs
        actual_context = 'wstack'
        print("Will do hybrid w stack/w projection, %d w slabs, %d w planes, support %d, w step %.1f" %
              (nwslabs, nwplanes, support, wstep))
    else:
        print("Will do 2d processing")
        # Simple 2D
        actual_context = '2d'
        vis_slices = 1
        wstep = 1e15
        nwplanes = 1
    
    model_list = [arlexecute.execute(create_image_from_visibility)(v, npixel=npixel, cellsize=cellsize)
                  for v in vis_list]
    
    # Perform weighting. This is a collective computation, requiring all visibilities :(
    print("\nSetup of weighting")
    if weighting == 'uniform':
        print("Will apply uniform weighting")
        vis_list = weight_list_arlexecute_workflow(vis_list, model_list)
    
    if context == 'wprojection' or context == 'wprojectwstack':
        gcfcf_list = [arlexecute.execute(create_awterm_convolutionfunction)(m, nw=nwplanes, wstep=wstep,
                                                                            oversampling=args.oversampling,
                                                                            support=support,
                                                                            maxsupport=512)
                      for m in model_list]
        gcfcf_list = arlexecute.persist(gcfcf_list)
        gcfcf = arlexecute.compute(gcfcf_list[0], sync=True)
        cf = convert_convolutionfunction_to_image(gcfcf[1])
        cf.data = numpy.real(cf.data)
        export_image_to_fits(cf, "cf.fits")
    else:
        gcfcf_list = None
    
    ####################################################################################################################
    
    if mode == 'pipeline':
        print("\nRunning pipeline")
        result = continuum_imaging_list_arlexecute_workflow(vis_list, model_list, context=actual_context,
                                                            vis_slices=vis_slices,
                                                            facets=facets, use_serial_invert=use_serial_invert,
                                                            use_serial_predict=use_serial_predict,
                                                            niter=args.niter,
                                                            fractional_threshold=args.fractional_threshold,
                                                            threshold=args.threshold,
                                                            nmajor=args.nmajor, gain=0.1,
                                                            algorithm='mmclean',
                                                            nmoment=nmoment, findpeak='ARL',
                                                            scales=[0],
                                                            restore_facets=args.restore_facets,
                                                            psfwidth=1.0,
                                                            deconvolve_facets=args.deconvolve_facets,
                                                            deconvolve_overlap=args.deconvolve_overlap,
                                                            deconvolve_taper=args.deconvolve_taper,
                                                            timeslice='auto',
                                                            psf_support=256,
                                                            window_shape=window_shape,
                                                            window_edge=window_edge,
                                                            gcfcf=gcfcf_list,
                                                            return_moments=False)
        result = arlexecute.persist(result[2])
        restored = result[0]
        
        start = time.time()
        restored = arlexecute.compute(restored, sync=True)
        run_time = time.time() - start
        print("Processing took %.2f (s)" % run_time)
        
        print(qa_image(restored))
        
        title = target_ms.split('/')[-1].replace('.MS', ' restored image')
        show_image(restored, vmax=0.03, vmin=-0.003, title=title)
        plot_name = target_ms.split('/')[-1].replace('.MS', '_restored.jpg')
        plt.savefig(plot_name)
        plt.show(block=False)
        
        restored_name = target_ms.split('/')[-1].replace('.MS', '_restored.fits')
        print("Writing restored image to %s" % restored_name)
        export_image_to_fits(restored, restored_name)
    
    else:
        print("\nRunning invert")
        result = invert_list_arlexecute_workflow(vis_list, model_list, context=actual_context, vis_slices=nwplanes,
                                                 facets=facets, use_serial_invert=use_serial_invert,
                                                 gcfcf=gcfcf_list)
        result = sum_invert_results_arlexecute(result)
        result = arlexecute.persist(result)
        dirty = result[0]
        
        start = time.time()
        dirty = arlexecute.compute(dirty, sync=True)
        run_time = time.time() - start
        print("Processing took %.2f (s)" % run_time)
        
        print(qa_image(dirty))
        
        title = target_ms.split('/')[-1].replace('.MS', ' dirty image')
        show_image(dirty, vmax=0.03, vmin=-0.003, title=title)
        plot_name = target_ms.split('/')[-1].replace('.MS', '_dirty.jpg')
        plt.savefig(plot_name)
        plt.show(block=False)
        
        dirty_name = target_ms.split('/')[-1].replace('.MS', '_dirty.fits')
        print("Writing dirty image to %s" % dirty_name)
        export_image_to_fits(dirty, dirty_name)
    
    if not serial:
        arlexecute.close()
    
    print("\nSKA LOW imaging using ARL")
    print("Started at  %s" % start_epoch)
    print("Finished at %s" % time.asctime())
