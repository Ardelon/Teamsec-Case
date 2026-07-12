#[derive(Debug, Clone, Default)]
pub struct WelfordProfiler {
    pub count: u64,
    pub current_mean: f64,
    pub current_m2: f64,
    pub minimum_value: f64,
    pub maximum_value: f64,
    pub null_count: u64,
    initialized: bool,
}

impl WelfordProfiler {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn observe(&mut self, value: Option<f64>) {
        match value {
            None => self.null_count += 1,
            Some(v) => {
                if !self.initialized {
                    self.minimum_value = v;
                    self.maximum_value = v;
                    self.initialized = true;
                } else {
                    self.minimum_value = self.minimum_value.min(v);
                    self.maximum_value = self.maximum_value.max(v);
                }

                self.count += 1;
                let delta = v - self.current_mean;
                self.current_mean += delta / self.count as f64;
                let delta2 = v - self.current_mean;
                self.current_m2 += delta * delta2;
            }
        }
    }

    pub fn variance(&self) -> f64 {
        if self.count < 2 {
            0.0
        } else {
            self.current_m2 / (self.count as f64 - 1.0)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn computes_mean_and_variance() {
        let mut profiler = WelfordProfiler::new();
        profiler.observe(Some(2.0));
        profiler.observe(Some(4.0));
        profiler.observe(Some(6.0));
        profiler.observe(None);

        assert_eq!(profiler.count, 3);
        assert_eq!(profiler.null_count, 1);
        assert!((profiler.current_mean - 4.0).abs() < f64::EPSILON);
        assert!((profiler.variance() - 4.0).abs() < f64::EPSILON);
        assert_eq!(profiler.minimum_value, 2.0);
        assert_eq!(profiler.maximum_value, 6.0);
    }
}
