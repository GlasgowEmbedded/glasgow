Hardware revisions
------------------

.. hint::

    The devices manufactured by 1BitSquared and :ref:`sold by CrowdSupply and Mouser <purchasing>` use the hardware revision ``revC3``.

The Glasgow hardware evolves over time, with each major milestone called a "revision". Although all revisions are, and will always be supported with the latest software stack, they vary significantly in their capabilities, and the revision that is being used will determine which tasks can be achieved using the hardware.

Glasgow hardware revisions use the ``revXN`` format, where ``X`` is a revision letter (advanced alphabetically when major design changes are made) and ``N`` is a stepping number (incremented on any layout or component changes). For example, ``revC0`` is the first stepping of revision C.


.. _revD:

revD
####

Revision D is a planned future revision that extends the I/O pin count to 32 without substantially changing other functions.


.. _revC:

revC
####

.. image:: ./_images/3drender-revC2.png
    :alt: Overview of the Glasgow PCB

Revision C is the latest revision, first mass produced by `1bitSquared`_ at stepping ``revC3``. It provides 16 I/O pins with a data rate up to approx. 100 Mbps/pin (50 MHz) [#]_, independent direction control and independent programmable pull-up/pull-down resistors. The I/O pins are grouped into two I/O ports, each of which can use any voltage from 1.8 V to 5 V, sense and monitor I/O voltage of the device under test, as well as provide up to 150 mA of power. The board uses USB 2 for power, configuration, and communication, achieving up to 336 Mbps (42 MB/s) of sustained combined throughput.

.. _1bitSquared: https://1bitsquared.com/

.. [#] Data rate achievable in practice depends on many factors and will vary greatly with specific interface and applet design. 12 Mbps/pin (6 MHz) can be achieved with minimal development effort; reaching higher data rates requires careful HDL coding and a good understanding of timing analysis.


.. _revA:
.. _revB:

revA, revB
##########

Revisions A and B have not been produced in significant numbers, have major design issues, and are therefore mostly of historical interest. Nevertheless, anyone who has one of the revA/revB boards can keep using them—forever.
