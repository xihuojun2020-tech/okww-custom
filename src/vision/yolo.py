# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lazy production echo detection from an explicit package model path."""


class EchoDetector:
    def __init__(self, weights):
        self.weights = str(weights)
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect
            self._model = OpenVinoYolo8Detect(weights=self.weights)
        return self._model

    def detect(self, image, threshold=.6, label=-1):
        return self.model.detect(image, threshold=threshold, label=label)
