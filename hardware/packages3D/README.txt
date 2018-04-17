Sources:

 * 87834-2019.stp: http://www.molex.com/molex/part/partModels.jsp?&prodLevel=part&series=&partNo=878342019&channel=Products
   (non-free)
 * LED_0603_1608Metric_Castellated.{step,wrl}: cadquery stock
 * QFN-56-1EP_8x8mm_Pitch0.5mm_EP5.2x4.5mm.{step,wrl}: cadquery custom
 * WQFN-20-1EP_4.5x2.5mm_Pitch0.5mm_EP2.9x1.0mm.{step,wrl}: cadquery custom

'QFN-56-1EP_8x8mm_Pitch0.5mm_EP5.2x4.5mm': Params( # from http://www.cypress.com/file/138911/download
    c = 0.2,        # pin thickness, body center part height
#    K=0.2,          # Fillet radius for pin edges
    L = 0.4,        # pin top flat part length (including fillet radius)
    fp_s = True,     # True for circular pinmark, False for square pinmark (useful for diodes)
    fp_r = 0.5,     # first pin indicator radius
    fp_d = 0.2,     # first pin indicator distance from edge
    fp_z = 0.01,     # first pin indicator depth
    ef = 0.0, # 0.05,      # fillet of edges  Note: bigger bytes model with fillet
    cce = 0.3,      # chamfer of the epad 1st pin corner
    D = 8.0,       # body overall length
    E = 8.0,       # body overall width
    A1 = 0.02,  # body-board separation  maui to check
    A2 = 0.98,  # body height
    b = 0.25,  # pin width
    e = 0.5,  # pin (center-to-center) distance
    m = 0.0,  # margin between pins and body
    ps = 'rounded',   # rounded pads
    npx = 14,  # number of pins along X axis (width)
    npy = 14,  # number of pins along y axis (length)
    epad = (5.2,4.5), # e Pad
    excluded_pins = None, #no pin excluded
    modelName = 'QFN-56-1EP_8x8mm_Pitch0.5mm_EP5.2x4.5mm', #modelName
    rotation = -90, # rotation if required
    dest_dir_prefix = '../Housings_DFN_QFN.3dshapes/'
    ),
'WQFN-20-1EP_4.5x2.5mm_Pitch0.5mm_EP2.9x1.0mm': Params( # from http://www.onsemi.com/pub/Collateral/505AB.PDF
    c = 0.2,        # pin thickness, body center part height
#    K=0.2,          # Fillet radius for pin edges
    L = 0.4,        # pin top flat part length (including fillet radius)
    fp_s = True,     # True for circular pinmark, False for square pinmark (useful for diodes)
    fp_r = 0.5,     # first pin indicator radius
    fp_d = 0.1,     # first pin indicator distance from edge
    fp_z = 0.01,     # first pin indicator depth
    ef = 0.0,       # fillet of edges  Note: bigger bytes model with fillet
    cce = 0.25,      # chamfer of the epad 1st pin corner
    D = 4.5,       # body overall length
    E = 2.5,       # body overall width
    A1 = 0.02,  # body-board separation  maui to check
    A2 = 0.78,  # body height
    b = 0.24,  # pin width
    e = 0.5,  # pin (center-to-center) distance
    m = 0.0,  # margin between pins and body
    ps = 'rounded',   # rounded pads
    npx = 8,  # number of pins along X axis (width)
    npy = 2,  # number of pins along y axis (length)
    epad = (2.9,1.0), # e Pad
    excluded_pins = None, #no pin excluded
    modelName = 'WQFN-20-1EP_4.5x2.5mm_Pitch0.5mm_EP2.9x1.0mm', #modelName
    rotation = -90, # rotation if required
    dest_dir_prefix = '../Housings_DFN_QFN.3dshapes/'
    ),
