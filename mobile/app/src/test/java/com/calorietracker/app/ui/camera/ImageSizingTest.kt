package com.calorietracker.app.ui.camera

import org.junit.Assert.assertEquals
import org.junit.Test

class ImageSizingTest {

    @Test
    fun sampleSize_keepsLongSideAtLeastTarget() {
        // 12 MP sensor: 4032 / 2 = 2016, / 4 = 1008 < 1024, so 2 is the largest safe power of two.
        assertEquals(2, sampleSizeFor(4032, 3024))
        assertEquals(2, sampleSizeFor(3024, 4032))
        // 4096 / 4 = 1024 is still >= target.
        assertEquals(4, sampleSizeFor(4096, 3072))
        assertEquals(8, sampleSizeFor(8192, 6144))
    }

    @Test
    fun sampleSize_isOneForSmallOrInvalidImages() {
        assertEquals(1, sampleSizeFor(1024, 768))
        assertEquals(1, sampleSizeFor(2047, 100))
        assertEquals(1, sampleSizeFor(640, 480))
        assertEquals(1, sampleSizeFor(0, 0))
        assertEquals(1, sampleSizeFor(-1, 500))
    }

    @Test
    fun targetSize_scalesLongSideTo1024KeepingAspect() {
        assertEquals(Size2(1024, 768), targetSize(4032, 3024))
        assertEquals(Size2(768, 1024), targetSize(3024, 4032))
        assertEquals(Size2(1024, 576), targetSize(1920, 1080))
        assertEquals(Size2(1024, 1024), targetSize(3000, 3000))
    }

    @Test
    fun targetSize_neverUpscales() {
        assertEquals(Size2(800, 600), targetSize(800, 600))
        assertEquals(Size2(1024, 10), targetSize(1024, 10))
    }

    @Test
    fun targetSize_keepsAtLeastOnePixel() {
        assertEquals(Size2(1024, 1), targetSize(100_000, 10))
    }

    @Test
    fun sampleThenScale_endsAtTarget() {
        val s = sampleSizeFor(4032, 3024)
        val decoded = targetSize(4032 / s, 3024 / s)
        assertEquals(Size2(1024, 768), decoded)
    }
}
