import pandas as pd


# 加载CSV文件，假设文件没有列名

def load_csv_without_header(file_path, column_name='Column1'):
    # 使用header=None表示没有列名，并通过names指定列名

    df = pd.read_csv(file_path, header=None, names=[column_name])

    return df


# 分析数据

def analyze_data(df, column_name):
    # 直接使用列名访问数据

    data = df[column_name]

    # 计算统计量

    stats = {

        '最小值': data.min(),

        '平均数': data.mean(),

        '中位数': data.median(),

        '最大值': data.max(),

        '25%位数': data.quantile(0.25),

        '75%位数': data.quantile(0.75)

    }

    # 打印统计量

    for key, value in stats.items():
        print(f"{key}: {value}")

    # 主函数


def main():
    file_path = 'cpNode3_output.csv'  # 替换为你的CSV文件路径

    column_name = 'Value'  # 为你的列指定一个名称

    df = load_csv_without_header(file_path, 'Column1')

    analyze_data(df, 'Column1')


if __name__ == "__main__":
    main()