# This code is part of Qiskit.
#
# (C) Copyright IBM 2021.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests that hit all the basic server endpoints using both a public and premium provider."""

import time
from datetime import datetime, timedelta

from qiskit import transpile
from qiskit.test import slow_test
from qiskit.test.reference_circuits import ReferenceCircuits

from qiskit_ibm_provider import least_busy
from qiskit_ibm_provider.exceptions import IBMBackendJobLimitError
from ..decorators import requires_providers
from ..ibm_test_case import IBMTestCase
from ..utils import cancel_job


class TestBasicServerPaths(IBMTestCase):
    """Test the basic server endpoints using both a public and premium provider."""

    @classmethod
    @requires_providers
    def setUpClass(cls, provider, hgps):
        # pylint: disable=arguments-differ
        super().setUpClass()
        cls.provider = provider  # Dict[str, IBMProvider]
        cls.hgps = hgps
        cls.last_week = datetime.now() - timedelta(days=7)

    @slow_test
    def test_job_submission(self):
        """Test running a job against a device."""
        for desc, hgp in self.hgps.items():
            backend = least_busy(
                self.provider.backends(
                    simulator=False,
                    filters=lambda b: b.configuration().n_qubits >= 5,
                    **hgp
                )
            )
            with self.subTest(desc=desc, backend=backend):
                job = self._submit_job_with_retry(ReferenceCircuits.bell(), backend)

                # Fetch the results.
                result = job.result()
                self.assertTrue(result.success)

                # Fetch the circuits.
                circuit = self.provider.backend.job(job.job_id()).circuits()
                self.assertEqual(circuit, job.circuits())

    def test_job_backend_properties_and_status(self):
        """Test the backend properties and status of a job."""
        for desc, hgp in self.hgps.items():
            backend = self.provider.backends(
                simulator=False,
                operational=True,
                filters=lambda b: b.configuration().n_qubits >= 5,
                **hgp
            )[0]
            with self.subTest(desc=desc, backend=backend):
                job = self._submit_job_with_retry(ReferenceCircuits.bell(), backend)
                self.assertIsNotNone(job.properties())
                self.assertTrue(job.status())
                # Cancel job so it doesn't consume more resources.
                cancel_job(job, verify=True)

    def test_retrieve_jobs(self):
        """Test retrieving jobs."""
        backend_name = "ibmq_qasm_simulator"
        for desc, hgp in self.hgps.items():
            backend = self.provider.get_backend(backend_name, **hgp)
            with self.subTest(desc=desc, backend=backend):
                job = self._submit_job_with_retry(ReferenceCircuits.bell(), backend)
                job_id = job.job_id()

                retrieved_jobs = self.provider.backend.jobs(
                    backend_name=backend_name,
                    start_datetime=self.last_week,
                    ignore_composite_jobs=True,
                )
                self.assertGreaterEqual(len(retrieved_jobs), 1)
                retrieved_job_ids = {job.job_id() for job in retrieved_jobs}
                self.assertIn(job_id, retrieved_job_ids)

    def test_device_properties_and_defaults(self):
        """Test the properties and defaults for an open pulse device."""
        for desc, hgp in self.hgps.items():
            pulse_backends = self.provider.backends(
                open_pulse=True, operational=True, **hgp
            )
            if not pulse_backends:
                raise self.skipTest(
                    "Skipping pulse test since no pulse backend "
                    'found for "{}"'.format(desc)
                )

            pulse_backend = pulse_backends[0]
            with self.subTest(desc=desc, backend=pulse_backend):
                self.assertIsNotNone(pulse_backend.properties())
                self.assertIsNotNone(pulse_backend.defaults())

    def test_device_status_and_job_limit(self):
        """Test the status and job limit for a device."""
        for desc, hgp in self.hgps.items():
            backend = self.provider.backends(simulator=False, operational=True, **hgp)[
                0
            ]
            with self.subTest(desc=desc, backend=backend):
                self.assertTrue(backend.status())
                job_limit = backend.job_limit()
                if desc == "public_provider":
                    self.assertIsNotNone(job_limit.maximum_jobs)
                self.assertTrue(job_limit)

    def _submit_job_with_retry(self, circs, backend, max_retry=5):
        """Retry submitting a job if limit is reached."""
        limit_error = None
        transpiled = transpile(circs, backend)
        for _ in range(max_retry):
            try:
                job = backend.run(transpiled)
                return job
            except IBMBackendJobLimitError as err:
                limit_error = err
                time.sleep(1)

        return self.fail(
            "Unable to submit job after {} retries: {}".format(max_retry, limit_error)
        )
