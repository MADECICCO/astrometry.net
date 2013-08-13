import numpy as np
import scipy.interpolate as interp
from miscutils import lanczos_filter

# DEBUG
from astrometry.util.plotutils import *
import pylab as plt

class ResampleError(Exception):
    pass
class OverlapError(ResampleError):
    pass
class NoOverlapError(OverlapError):
    pass
class SmallOverlapError(OverlapError):
    pass

def resample_with_wcs(targetwcs, wcs, Limages, L, spline=True,
                      splineFallback = True,
                      splineStep = 25,
                      splineMargin = 12):
    '''
    Returns (Yo,Xo, Yi,Xi, ims)

    Use the results like:

    target[Yo,Xo] = nearest_neighbour[Yi,Xi]
    # or
    target[Yo,Xo] = ims[i]


    raises NoOverlapError if the target and input WCSes do not
    overlap.  Raises SmallOverlapError if they do not overlap "enough"
    (as described below).

    targetwcs, wcs: duck-typed WCS objects that must have:
       - properties "imagew", "imageh"
       - methods  "r,d = pixelxy2radec(x, y)"
       -          "ok,x,y = radec2pixelxy(ra, dec)"

    The WCS functions are expected to operate in FITS pixel-indexing.

    The WCS function must support 1-d, broadcasting, vectorized
    pixel<->radec calls.

    Limages: list of images to Lanczos-interpolate at the given Lanczos order.
    If empty, just returns nearest-neighbour indices.

    L: int, lanczos order

    spline: bool: use a spline interpolator to reduce the number of
    WCS calls.

    splineFallback: bool: the spline requires a certain amount of
    spatial overlap.  With splineFallback = True, fall back to
    non-spline version.  With splineFallback = False, just raises
    SmallOverlapError.

    splineStep: approximate grid size

    '''
    # Adapted from detection/sdss-demo.py

    ### DEBUG
    #ps = PlotSequence('resample')
    ps = None

    H,W = int(targetwcs.imageh), int(targetwcs.imagew)
    h,w = int(      wcs.imageh), int(      wcs.imagew)

    for im in Limages:
        assert(im.shape == (h,w))

    #print 'Target size', W, H
    #print 'Input size', w, h
    
    # First find the approximate bbox of the input image in
    # the target image so that we don't ask for way too
    # many out-of-bounds pixels...
    XY = []
    for x,y in [(0,0), (w-1,0), (w-1,h-1), (0, h-1)]:
        ra,dec = wcs.pixelxy2radec(float(x + 1), float(y + 1))
        ok,xw,yw = targetwcs.radec2pixelxy(ra, dec)
        XY.append((xw - 1, yw - 1))
    XY = np.array(XY)

    x0,y0 = np.round(XY.min(axis=0)).astype(int)
    x1,y1 = np.round(XY.max(axis=0)).astype(int)
    if spline:
        # Now we build a spline that maps "target" pixels to "input" pixels
        # spline inputs: pixel coords in the 'target' image
        margin = splineMargin
        step = splineStep
        xlo = max(0, x0-margin)
        xhi = min(W, x1+margin)
        nx = np.ceil(float(xhi - xlo) / step) + 1
        xx = np.linspace(xlo, xhi, nx)
        ylo = max(0, y0-margin)
        yhi = min(H, y1+margin)
        ny = np.ceil(float(yhi - ylo) / step) + 1
        yy = np.linspace(ylo, yhi, ny)

        if ps:
            def expand_axes():
                M = 100
                ax = plt.axis()
                plt.axis([ax[0]-M, ax[1]+M, ax[2]-M, ax[3]+M])
                plt.axis('scaled')

            plt.clf()
            plt.plot(XY[:,0], XY[:,1], 'ro')
            plt.plot(xx, np.zeros_like(xx), 'b.')
            plt.plot(np.zeros_like(yy), yy, 'c.')
            plt.plot(xx, np.zeros_like(xx)+max(yy), 'b.')
            plt.plot(max(xx) + np.zeros_like(yy), yy, 'c.')
            plt.plot([0,W,W,0,0], [0,0,H,H,0], 'k-')
            plt.title('A: Target image: bbox')
            expand_axes()
            ps.savefig()

        if (len(xx) == 0) or (len(yy) == 0):
            #print 'No overlap between input and target WCSes'
            raise NoOverlapError()

        if (len(xx) <= 3) or (len(yy) <= 3):
            #print 'Not enough overlap between input and target WCSes'
            if splineFallback:
                spline = False
            else:
                raise SmallOverlapError()

    if spline:
        # spline outputs -- pixel coords in the 'input' image

        #rr,dd = targetwcs.pixelxy2radec(xx + 1, yy + 1)
        #ok,Xo,Yo = wcs.radec2pixelxy(rr, dd)
        # del rr
        # del dd
        #rr,dd = 
        ok,Xo,Yo = wcs.radec2pixelxy(
            *targetwcs.pixelxy2radec(
                xx[np.newaxis,:] + 1,
                yy[:,np.newaxis] + 1))
        Xo -= 1.
        Yo -= 1.
        del ok

        if ps:
            plt.clf()
            plt.plot(Xo, Yo, 'b.')
            plt.plot([0,w,w,0,0], [0,0,h,h,0], 'k-')
            plt.title('B: Input image')
            expand_axes()
            ps.savefig()
    
        xspline = interp.RectBivariateSpline(xx, yy, Xo.T)
        yspline = interp.RectBivariateSpline(xx, yy, Yo.T)
        del Xo
        del Yo

    else:
        margin = 0

    # Now, build the full pixel grid we want to interpolate...
    ixo = np.arange(max(0, x0-margin), min(W, x1+margin+1), dtype=int)
    iyo = np.arange(max(0, y0-margin), min(H, y1+margin+1), dtype=int)

    if len(ixo) == 0 or len(iyo) == 0:
        raise NoOverlapError()

    if spline:
        # And run the interpolator.  [xy]spline() does a meshgrid-like broadcast,
        # so fxi,fyi have shape n(iyo),n(ixo)
        # f[xy]i: floating-point pixel coords in the input image
        fxi = xspline(ixo, iyo).T
        fyi = yspline(ixo, iyo).T

        if ps:
            plt.clf()
            plt.plot(ixo, np.zeros_like(ixo), 'r,')
            plt.plot(np.zeros_like(iyo), iyo, 'm,')
            plt.plot(ixo, max(iyo) + np.zeros_like(ixo), 'r,')
            plt.plot(max(ixo) + np.zeros_like(iyo), iyo, 'm,')
            plt.plot([0,W,W,0,0], [0,0,H,H,0], 'k-')
            plt.title('C: Target image; i*o')
            expand_axes()
            ps.savefig()
    
            plt.clf()
            plt.plot(fxi, fyi, 'r,')
            plt.plot([0,w,w,0,0], [0,0,h,h,0], 'k-')
            plt.title('D: Input image, f*i')
            expand_axes()
            ps.savefig()

    else:
        # fxi = np.empty((len(iyo),len(ixo)))
        # fyi = np.empty((len(iyo),len(ixo)))
        # fxo = (ixo).astype(float) + 1.
        # fyo = np.empty_like(fxo)
        # for i,y in enumerate(iyo):
        #     fyo[:] = y + 1.
        #     # Assume 1-d vectorized pixel<->radec
        #     ra,dec = targetwcs.pixelxy2radec(fxo, fyo)
        #     ok,x,y = wcs.radec2pixelxy(ra, dec)
        #     fxi[i,:] = x - 1.
        #     fyi[i,:] = y - 1.

        ok,fxi,fyi = wcs.radec2pixelxy(
            *targetwcs.pixelxy2radec(ixo[np.newaxis,:] + 1., iyo[:,np.newaxis] + 1.))
        del ok
        fxi -= 1.
        fyi -= 1.
        
    # print 'ixo', ixo.shape
    # print 'iyo', iyo.shape
    # print 'fxi', fxi.shape
    # print 'fyi', fyi.shape

    # i[xy]i: int coords in the input image
    ixi = np.round(fxi).astype(int)
    iyi = np.round(fyi).astype(int)

    # Keep only in-bounds pixels.
    I = np.flatnonzero((ixi >= 0) * (iyi >= 0) * (ixi < w) * (iyi < h))
    fxi = fxi.flat[I]
    fyi = fyi.flat[I]
    ixi = ixi.flat[I]
    iyi = iyi.flat[I]
    #print 'I', I.shape
    #print 'dims', (len(iyo),len(ixo))
    iy,ix = np.unravel_index(I, (len(iyo),len(ixo)))
    iyo = iyo[0] + iy
    ixo = ixo[0] + ix
    #ixo = ixo[I % len(ixo)]
    #iyo = iyo[I / len(ixo)]
    # i[xy]o: int coords in the target image

    if spline and ps:
        plt.clf()
        plt.plot(ixo, iyo, 'r,')
        plt.plot([0,W,W,0,0], [0,0,H,H,0], 'k-')
        plt.title('E: Target image; i*o')
        expand_axes()
        ps.savefig()

        plt.clf()
        plt.plot(fxi, fyi, 'r,')
        plt.plot([0,w,w,0,0], [0,0,h,h,0], 'k-')
        plt.title('F: Input image, f*i')
        expand_axes()
        ps.savefig()

    assert(np.all(ixo >= 0))
    assert(np.all(iyo >= 0))
    assert(np.all(ixo < W))
    assert(np.all(iyo < H))

    assert(np.all(ixi >= 0))
    assert(np.all(iyi >= 0))
    assert(np.all(ixi < w))
    assert(np.all(iyi < h))

    if len(Limages):
        fxi -= ixi
        fyi -= iyi
        dx = fxi
        dy = fyi
        del fxi
        del fyi

        # Lanczos interpolation.
        # number of pixels
        nn = len(ixo)
        NL = 2*L+1

        # We interpolate all the pixels at once.

        # accumulators for each input image
        laccs = [np.zeros(nn) for im in Limages]
        _lanczos_interpolate(L, ixi, iyi, dx, dy, laccs, Limages)
        rims = laccs

    else:
        rims = []

    return (iyo,ixo, iyi,ixi, rims)


def _lanczos_interpolate(L, ixi, iyi, dx, dy, laccs, limages):
    '''
    L: int, Lanczos order
    ixi: int, 1-d numpy array, len n, x coord in input images
    iyi:     ----""----        y
    dx: float, 1-d numpy array, len n, fractional x coord
    dy:      ----""----                    y
    laccs: list of [float, 1-d numpy array, len n]: outputs
    limages list of [float, 2-d numpy array, shape h,w]: inputs
    '''

    lfunc = lanczos_filter
    if L == 3:
        try:
            from util import lanczos3_filter, lanczos3_filter_table
            #lfunc = lambda nil,x,y: lanczos3_filter(x,y)
            lfunc = lambda nil,x,y: lanczos3_filter_table(x,y)
        except:
            pass

    h,w = limages[0].shape
    n = len(ixi)
    # sum of lanczos terms
    fsum = np.zeros(n)
    off = np.arange(-L, L+1)
    fx = np.zeros(n)
    fy = np.zeros(n)
    for oy in off:
        lfunc(L, -oy + dy, fy)
        for ox in off:
            lfunc(L, -ox + dx, fx)
            for lacc,im in zip(laccs, limages):
                lacc += fx * fy * im[np.clip(iyi + oy, 0, h-1),
                                     np.clip(ixi + ox, 0, w-1)]
                fsum += fx*fy
    for lacc in laccs:
        lacc /= fsum



if __name__ == '__main__':
    import fitsio
    from astrometry.util.util import Sip,Tan
    import time
    
    ra,dec = 219.577111, 54.52
    pixscale = 2.75 / 3600.
    #W,H = 2048, 2048
    W,H = 512, 512
    cowcs = Tan(ra, dec, (W+1)/2., (H+1)/2.,
                -pixscale, 0., 0., pixscale, W, H)
    cowcs.write_to('co.wcs')
    
    intfn = '05579a167-w1-int-1b.fits'

    wcs = Sip(intfn)
    pix = fitsio.read(intfn)
    pix[np.logical_not(np.isfinite(pix))] = 0.
    
    t0 = time.clock()
    Yo,Xo,Yi,Xi,ims = resample_with_wcs(cowcs, wcs, [pix], 3)
    t1 = time.clock()

    print 'Resampling took', t1-t0
    
    out = np.zeros((H,W))
    out[Yo,Xo] = ims[0]
    fitsio.write('resampled.fits', out, clobber=True)
