# ML lectures index

> The lecture folder is local only; every teammate must place it in the repo root.
> Folder: `лекции по Машинному обучению/` (pptx, ignored by git). Titles and topics only — no lecture content here.
> How to use: see "ML work rule" in [CLAUDE.md](../CLAUDE.md). To read slides without PowerPoint, unzip the pptx and
> take the `<a:t>` text from `ppt/slides/slideN.xml`.

| File | Topic | Helps our tasks with |
|---|---|---|
| `Занятие_2_Предобработка_данных.pptx` | Data preprocessing: missing values, variable types, duplicates, outliers, encoding, feature engineering, scaling | data preparation, duplicates in news, feature encoding, leakage in preprocessing, train/test split |
| `Занятие_3_Линейная_регрессия_и_градиентный_спуск_2_Repaired.pptx` | Linear regression, gradient descent, model diagnostics | baseline models, regression metrics, residual diagnostics, scaling |
| `Занятие_4_Регуляризация_и_кросс_валидация.pptx` | Regularization, cross-validation, multicollinearity, feature assembly | data split (dev/test, group-aware), cross-validation, leakage, regularization, tuning on dev only |
| `Занятие_5_Логистическая_регрессия_и_метрики.pptx` | Logistic regression, classification metrics, threshold and error cost, class imbalance | relevance / impact / urgency classifiers, precision/recall/F1/ROC, threshold choice, imbalance, baseline comparison |
| `Занятие_6_Наивный_Байес.pptx` | Naive Bayes (incl. texts), SVM, kernels, model selection | text classification baselines (bag of words, TF-IDF), imbalance, scaling, model comparison |
| `Занятие_7_Деревья_решений_и_ансамбли.pptx` | Decision trees, ensembles (bagging, random forest), model choice | trees/ensembles, categorical features, confidence intervals (bootstrap), cross-validation |
| `Занятие_8_Градиентный_бустинг_и_интерпретируемость_13.pptx` | Gradient boosting, its implementations, interpretability (SHAP) | boosting for ranking/scoring, categorical and missing values, feature importance, explaining a score |
| `Занятие_9_Кластеризация_и_снижение_размерности.pptx` | Clustering (k-means, hierarchical), choosing k, cluster stability, dimensionality reduction | news story clustering/dedup, embeddings evaluation, scaling before distance, cluster quality metrics |
| `Занятие_10_Нейронные_сети_с_нуля.pptx` | Neural networks from scratch: neuron, architecture, training, problems, regularization and optimization | understanding embedding models, overfitting, scaling inputs |
| `Доп_занятие_Временные_ряды_и_прогнозирование.pptx` | Time series and forecasting: dependence of observations, decomposition, honest evaluation, baselines, classic models, ML on series | time-ordered split for news (no future leakage), baselines, metrics (MAPE trap, MASE), prediction intervals, market data |
