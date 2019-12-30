pytest with enhancements
========================

This is a fork of pytest with enhancements that have been rejected upstream,
have stalled there, or are not really fitting.

This is mainly for getting things done, and having things here that I like better.

I have started with https://github.com/blueyed/pytest-enhancements, but figured
that it is more sane to have a personal fork than a plugin that has to
monkeypatch pytest anyway.

It also allows for having CI etc (in contrast to having this only in a local
integration branch).

------

.. image:: https://codecov.io/gh/blueyed/pytest/branch/my-master/graph/badge.svg
    :target: https://codecov.io/gh/blueyed/pytest
    :alt: Code coverage Status

.. image:: https://travis-ci.org/blueyed/pytest.svg?branch=my-master
    :target: https://travis-ci.org/blueyed/pytest

The ``pytest`` framework makes it easy to write small tests, yet
scales to support complex functional testing for applications and libraries.

An example of a simple test:

.. code-block:: python

    # content of test_sample.py
    def inc(x):
        return x + 1


    def test_answer():
        assert inc(3) == 5


To execute it::

    $ pytest
    ============================= test session starts =============================
    collected 1 items

    test_sample.py F

    ================================== FAILURES ===================================
    _________________________________ test_answer _________________________________

        def test_answer():
    >       assert inc(3) == 5
    E       assert 4 == 5
    E        +  where 4 = inc(3)

    test_sample.py:5: AssertionError
    ========================== 1 failed in 0.04 seconds ===========================


Due to ``pytest``'s detailed assertion introspection, only plain ``assert`` statements are used. See `getting-started <https://docs.pytest.org/en/latest/getting-started.html#our-first-test-run>`_ for more examples.


Features
--------

- Detailed info on failing `assert statements <https://docs.pytest.org/en/latest/assert.html>`_ (no need to remember ``self.assert*`` names);

- `Auto-discovery
  <https://docs.pytest.org/en/latest/goodpractices.html#python-test-discovery>`_
  of test modules and functions;

- `Modular fixtures <https://docs.pytest.org/en/latest/fixture.html>`_ for
  managing small or parametrized long-lived test resources;

- Can run `unittest <https://docs.pytest.org/en/latest/unittest.html>`_ (or trial),
  `nose <https://docs.pytest.org/en/latest/nose.html>`_ test suites out of the box;

- Python 3.5+ and PyPy3;

- Rich plugin architecture, with over 315+ `external plugins <http://plugincompat.herokuapp.com>`_ and thriving community;


Documentation
-------------

For full documentation, including installation, tutorials and PDF documents, please see https://docs.pytest.org/en/latest/.


Bugs/Requests
-------------

Please use the `GitHub issue tracker <https://github.com/blueyed/pytest/issues>`_ to submit bugs or request features.


Changelog
---------

Consult the `Changelog <https://docs.pytest.org/en/latest/changelog.html>`__ page for fixes and enhancements of each version.


Support pytest
--------------

`Open Collective`_ is an online funding platform for open and transparent communities.
It provide tools to raise money and share your finances in full transparency.

It is the platform of choice for individuals and companies that want to make one-time or
monthly donations directly to the project.

See more details in the `pytest collective`_.

.. _Open Collective: https://opencollective.com
.. _pytest collective: https://opencollective.com/pytest


pytest for enterprise
---------------------

Available as part of the Tidelift Subscription.

The maintainers of pytest and thousands of other packages are working with Tidelift to deliver commercial support and
maintenance for the open source dependencies you use to build your applications.
Save time, reduce risk, and improve code health, while paying the maintainers of the exact dependencies you use.

`Learn more. <https://tidelift.com/subscription/pkg/pypi-pytest?utm_source=pypi-pytest&utm_medium=referral&utm_campaign=enterprise&utm_term=repo>`_

Security
^^^^^^^^

pytest has never been associated with a security vulnerability, but in any case, to report a
security vulnerability please use the `Tidelift security contact <https://tidelift.com/security>`_.
Tidelift will coordinate the fix and disclosure.


License
-------

Copyright Holger Krekel and others, 2004-2019.

Distributed under the terms of the `MIT`_ license, pytest is free and open source software.

.. _`MIT`: https://github.com/pytest-dev/pytest/blob/master/LICENSE
