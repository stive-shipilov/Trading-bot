#include <QApplication>
#include <QTcpSocket>
#include <QJsonDocument>
#include <QJsonObject>
#include <QVBoxLayout>
#include <QLabel>
#include <QTableWidget>
#include <QComboBox>
#include <QPushButton>
#include <QDebug>
#include <memory>
#include <vector>
#include <unordered_map>
#include <deque>
#include <fstream>
#include <iostream>

// Класс сделки
struct Trade {
    std::string company;
    std::string action;
    double price;
    int amount;
    std::string timestamp;

    friend std::ostream& operator<<(std::ostream& os, const Trade& trade) {
        return os << "[Trade] " << trade.company << " | " << trade.action << " | $" << trade.price
                  << " | " << trade.amount << " units | " << trade.timestamp;
    }
};

// Кошелёк с несколькими валютами
class Wallet {
private:
    std::unordered_map<std::string, double> balances = {
        {"USD", 10000.15}, {"EUR", 8000.00}, {"BTC", 0.5}
    };
    std::unordered_map<std::string, double> exchangeRates = {
        {"USD", 1.0}, {"EUR", 1.1}, {"BTC", 45000.0}
    };

public:
    void updateBalance(double newBalance) {
        balances["USD"] = newBalance;
    }

    double getBalance(const std::string& currency) const {
        return balances.at(currency) * exchangeRates.at(currency);
    }
};

// Класс истории сделок
class TradeHistory {
private:
    std::deque<Trade> trades;
    std::unordered_map<std::string, std::vector<Trade>> tradeMap;
    static constexpr size_t MAX_HISTORY = 10;

public:
    void addTrade(const Trade& trade) {
        if (trades.size() >= MAX_HISTORY) {
            trades.pop_front();
        }
        trades.push_back(trade);
        tradeMap[trade.company].push_back(trade);
        saveToFile(trade);
    }

    void undoLastTrade() {
        if (!trades.empty()) {
            tradeMap[trades.back().company].pop_back();
            trades.pop_back();
        }
    }

    const std::vector<Trade>& getTrades(const std::string& company) const {
        static std::vector<Trade> empty;
        auto it = tradeMap.find(company);
        return (it != tradeMap.end()) ? it->second : empty;
    }

    void saveToFile(const Trade& trade) {
        std::ofstream file("trades.log", std::ios::app);
        if (file) {
            file << trade << std::endl;
        }
    }
};

// Класс сервера
class TradingBotServer : public QWidget {
    Q_OBJECT

private:
    std::unique_ptr<QComboBox> companyComboBox;
    std::unique_ptr<QComboBox> strategyComboBox;
    std::unique_ptr<QComboBox> currencyComboBox;
    std::unique_ptr<QTableWidget> tradeTable;
    std::unique_ptr<QLabel> walletLabel;
    std::unique_ptr<QPushButton> undoButton;
    std::unique_ptr<QTcpSocket> out;
    TradeHistory tradeHistory;
    Wallet wallet;
    std::string selectedCompany = "Не выбрано";
    std::string selectedCurrency = "USD";

public:
    explicit TradingBotServer(QWidget* parent = nullptr) : QWidget(parent) {
        setupUI();
        connectToPython();
    }

private:
    void setupUI() {
        companyComboBox = std::make_unique<QComboBox>(this);
        companyComboBox->addItems({"Не выбрано", "AAPL", "MSFT", "TSLA"});

        strategyComboBox = std::make_unique<QComboBox>(this);
        strategyComboBox->addItems({"Не выбрано", "EMA", "Moving Average"});

        currencyComboBox = std::make_unique<QComboBox>(this);
        currencyComboBox->addItems({"USD", "EUR", "BTC"});

        tradeTable = std::make_unique<QTableWidget>(this);
        tradeTable->setColumnCount(4);
        tradeTable->setHorizontalHeaderLabels({"Action", "Price", "Amount", "Timestamp"});

        walletLabel = std::make_unique<QLabel>(this);
        updateWalletUI();

        undoButton = std::make_unique<QPushButton>("Отменить последнюю сделку", this);

        QVBoxLayout* layout = new QVBoxLayout(this);
        layout->addWidget(walletLabel.get());
        layout->addWidget(new QLabel("Выберите компанию:"));
        layout->addWidget(companyComboBox.get());
        layout->addWidget(new QLabel("Выберите стратегию:"));
        layout->addWidget(strategyComboBox.get());
        layout->addWidget(new QLabel("Выберите валюту:"));
        layout->addWidget(currencyComboBox.get());
        layout->addWidget(tradeTable.get());
        layout->addWidget(undoButton.get());

        setLayout(layout);
        setWindowTitle("Trading Bot Interface");

        connect(companyComboBox.get(), &QComboBox::currentTextChanged, this, &TradingBotServer::onCompanyChanged);
        connect(strategyComboBox.get(), &QComboBox::currentTextChanged, this, &TradingBotServer::onStrategyChanged);
        connect(currencyComboBox.get(), &QComboBox::currentTextChanged, this, &TradingBotServer::onCurrencyChanged);
        connect(undoButton.get(), &QPushButton::clicked, this, &TradingBotServer::onUndoTrade);
    }

    void connectToPython() {
        out = std::make_unique<QTcpSocket>(this);
        connect(out.get(), &QTcpSocket::readyRead, this, &TradingBotServer::onReadyRead);
        out->connectToHost("localhost", 12346);
    }

    void updateWalletUI() {
        walletLabel->setText("Баланс: " + QString::number(wallet.getBalance(selectedCurrency), 'f', 2) + " " + QString::fromStdString(selectedCurrency));
    }

    void sendToPython(const QJsonObject& json) {
        QJsonDocument doc(json);
        out->write(doc.toJson());
    }

private slots:
    void onCompanyChanged(const QString& value) {
        selectedCompany = value.toStdString();
        QJsonObject json;
        json["type"] = "company";
        json["value"] = value;
        sendToPython(json);
        updateTradeTable();
    }

    void onStrategyChanged(const QString& value) {
        QJsonObject json;
        json["type"] = "strategy";
        json["value"] = value;
        sendToPython(json);
    }

    void onCurrencyChanged(const QString& value) {
        selectedCurrency = value.toStdString();
        updateWalletUI();
    }

    void onUndoTrade() {
        tradeHistory.undoLastTrade();
        updateTradeTable();
    }

    void onReadyRead() {
        QByteArray data = out->readAll();
        QJsonDocument doc = QJsonDocument::fromJson(data);
        if (doc.isObject()) {
            QJsonObject jsonObj = doc.object();

            wallet.updateBalance(jsonObj["balance"].toDouble());
            tradeHistory.addTrade({
                selectedCompany,
                jsonObj["action"].toString().toStdString(),
                jsonObj["price"].toDouble(),
                jsonObj["amount"].toInt(),
                jsonObj["timestamp"].toString().toStdString()
            });

            updateWalletUI();
            updateTradeTable();
        }
    }

    void updateTradeTable() {
        tradeTable->setRowCount(0);
        const auto& trades = tradeHistory.getTrades(selectedCompany);
        for (const auto& trade : trades) {
            int row = tradeTable->rowCount();
            tradeTable->insertRow(row);
            tradeTable->setItem(row, 0, new QTableWidgetItem(QString::fromStdString(trade.action)));
            tradeTable->setItem(row, 1, new QTableWidgetItem(QString::number(trade.price)));
            tradeTable->setItem(row, 2, new QTableWidgetItem(QString::number(trade.amount)));
            tradeTable->setItem(row, 3, new QTableWidgetItem(QString::fromStdString(trade.timestamp)));
        }
    }
};

int main(int argc, char* argv[]) {
    QApplication app(argc, argv);
    TradingBotServer server;
    server.show();
    return app.exec();
}

#include "main.moc"